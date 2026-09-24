import argparse
import json
import logging
import os
import signal
import socket
import threading
import time
from pathlib import Path
from ..core import ROOT
from ..server import Service,Server
from .contracts import Packages,Processor,NormalizerSink,RAW_TOPIC,NORMAL_TOPIC,QUARANTINE_TOPIC,TOPICS
from .clients import KafkaPublisher,KafkaConsumer,ClickHouse
from .metadata import Metadata,Gateway
from .archive import Archive

class FunctionSink:
    def __init__(self,fn):self.fn=fn
    def write(self,rows):self.fn(rows)

class ConfirmedSink:
    def __init__(self,sink,metadata,field):self.sink,self.meta,self.field=sink,metadata,field
    def write(self,rows):
        self.sink.write(rows)
        self.meta.mark(rows,self.field)

class LockedSink:
    def __init__(self,archive,metadata):self.archive,self.meta=archive,metadata
    def write(self,rows):
        receipts=[self.archive.put(r) for r in rows]
        self.meta.locked(rows,receipts)

class ConfirmedNormalizer:
    def __init__(self,publisher,packages,meta):self.publisher,self.packages,self.meta=publisher,packages,meta
    def write(self,rows):
        from .contracts import transform
        outputs=[transform(r,self.packages) for r in rows]
        self.publisher.publish(outputs)
        self.meta.mark([n for topic,n in outputs if topic==NORMAL_TOPIC],'normalized_at')


def dependencies():
    meta=Metadata(os.environ['NOVA_POSTGRES_DSN'])
    ch=ClickHouse(os.environ['NOVA_CLICKHOUSE_URL'],os.environ.get('NOVA_CLICKHOUSE_USER','nova'),os.environ['NOVA_CLICKHOUSE_PASSWORD'])
    config={'bootstrap.servers':os.environ['NOVA_KAFKA_BOOTSTRAP']}
    # An optional private file carries TLS/SASL configuration; credentials never appear in CLI arguments.
    if os.environ.get('NOVA_KAFKA_CONFIG_FILE'):
        config.update(json.loads(Path(os.environ['NOVA_KAFKA_CONFIG_FILE']).read_text()))
    return meta,ch,config

def initialize(meta,ch,config):
    from confluent_kafka.admin import AdminClient,NewTopic
    from confluent_kafka import KafkaException,KafkaError
    with meta.connect() as c:c.execute((ROOT/'deploy/postgres.sql').read_text())
    # No semicolons in literals in this fixed, bundled development DDL.
    for query in (ROOT/'deploy/clickhouse.sql').read_text().split(';'):
        query='\n'.join(line for line in query.splitlines() if not line.lstrip().startswith('--')).strip()
        if query:ch.request(query,json_result=False)
    replication=int(os.environ.get('NOVA_KAFKA_REPLICATION','1'))
    admin=AdminClient(config)
    futures=admin.create_topics([NewTopic(t,num_partitions=6,replication_factor=replication,config={'cleanup.policy':'delete','retention.ms':'604800000','min.insync.replicas':str(1 if replication==1 else 2)}) for t in TOPICS])
    for f in futures.values():
        try:f.result(30)
        except KafkaException as e:
            if e.args[0].code()!=KafkaError.TOPIC_ALREADY_EXISTS:raise

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description='Nova distributed development processes')
    parser.add_argument('role',choices=['init','gateway','relay','normalizer','indexer','detector','quarantine','archive'])
    role=parser.parse_args().role
    meta,ch,config=dependencies()
    packages=Packages(ROOT/'integrations').packages
    if role=='init':return initialize(meta,ch,config)
    if os.environ.get('NOVA_REQUIRE_HA')=='1':
        from .readiness import from_environment
        from_environment(meta,ch,config)
    if role=='gateway':
        credentials=json.loads(Path(os.environ['NOVA_CREDENTIALS_FILE']).read_text())
        service=Service(Gateway(meta,ch,packages),credentials)
        # Only compose publishes this port, on host loopback. Host/origin guards remain active.
        server=Server((os.environ.get('NOVA_BIND_ADDRESS','127.0.0.1'),8787),service)
        worker=threading.Thread(target=service.workflow_worker,daemon=True);worker.start()
        external=threading.Thread(target=service.external_worker,daemon=True);external.start()
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:
            service.stop.set();worker.join(timeout=20);external.join(timeout=20);server.server_close()
        return
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    worker_id=os.environ.get('HOSTNAME',socket.gethostname())+'-'+role
    consumer=None;processed=0;last_heartbeat=0
    try:
        if role=='relay':publisher=KafkaPublisher(config)
        else:
            topic={'normalizer':RAW_TOPIC,'archive':RAW_TOPIC,'indexer':NORMAL_TOPIC,'detector':NORMAL_TOPIC,'quarantine':QUARANTINE_TOPIC}[role]
            group='nova-archive-worm-v1' if role=='archive' and os.environ.get('NOVA_ARCHIVE_MODE')=='s3-object-lock' else 'nova-'+role+'-v1'
            consumer=KafkaConsumer(config,group,topic)
            if role=='normalizer':sink=ConfirmedNormalizer(KafkaPublisher(config),packages,meta)
            elif role=='indexer':sink=ConfirmedSink(ch,meta,'indexed_at')
            elif role=='detector':sink=FunctionSink(meta.detect)
            elif role=='quarantine':sink=FunctionSink(meta.quarantine)
            else:
                if os.environ.get('NOVA_ARCHIVE_MODE')=='s3-object-lock':
                    from ..retention import ObjectLockArchive
                    archive=ObjectLockArchive.from_environment()
                elif os.environ.get('NOVA_ARCHIVE_MODE','filesystem')=='filesystem':
                    archive=Archive(Path(os.environ['NOVA_ARCHIVE_DIRECTORY']).resolve())
                else:raise ValueError('unsupported archive mode')
                sink=LockedSink(archive,meta) if os.environ.get('NOVA_ARCHIVE_MODE')=='s3-object-lock' else ConfirmedSink(archive,meta,'archived_at')
            processor=Processor(consumer,sink)
        while not stop.is_set():
            n=meta.relay(publisher) if role=='relay' else processor.step()
            processed+=n
            if time.monotonic()-last_heartbeat>=5:
                meta.heartbeat(worker_id,role,processed);last_heartbeat=time.monotonic()
            if not n:stop.wait(.2)
    except Exception:
        try:meta.heartbeat(worker_id,role,processed,True)
        except Exception:pass
        # Error details may contain payloads/credentials from dependencies. Keep this default log generic.
        logging.error('%s stopped after unconfirmed delivery or invalid record; input offsets were not advanced for the failed batch',role)
        raise SystemExit(1)
    finally:
        if consumer:consumer.close()

if __name__=='__main__':main()
