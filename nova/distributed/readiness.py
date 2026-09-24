"""Fail-closed live durability preflight. Passing is not HA/DR qualification."""
from ..core import Problem
from .contracts import TOPICS

def check(meta,ch,topic_settings):
    with meta.connect() as c:
        pg=c.execute("SELECT current_setting('synchronous_commit') AS commit_mode,current_setting('synchronous_standby_names') AS standby,pg_is_in_recovery() AS recovery").fetchone()
        sync=c.execute("SELECT COUNT(*) AS n FROM pg_stat_replication WHERE state='streaming' AND sync_state IN ('sync','quorum')").fetchone()['n']
    if pg['recovery'] or pg['commit_mode'] not in ('on','remote_apply') or not pg['standby'] or sync<1:raise Problem('HA preflight: writable PostgreSQL with active synchronous standby required')
    for topic in TOPICS:
        info=topic_settings.get(topic)
        if not info or info.get('min_insync_replicas',0)<2 or info.get('unclean_leader_election') is not False:raise Problem('HA preflight: Kafka durability configuration failed')
        if not info.get('partitions') or any(p['replicas']<3 or p['isr']<2 for p in info['partitions']):raise Problem('HA preflight: Kafka replication or ISR insufficient')
    rows=ch.request("SELECT engine,is_readonly,is_session_expired,active_replicas,total_replicas FROM system.replicas WHERE database='nova' AND table='events' FORMAT JSON")
    if len(rows)!=1 or not str(rows[0]['engine']).startswith('Replicated') or any(int(rows[0][k]) for k in ('is_readonly','is_session_expired')) or min(int(rows[0]['active_replicas']),int(rows[0]['total_replicas']))<2:raise Problem('HA preflight: writable ClickHouse replicated table with two active replicas required')
    return {'durability_preflight':'passed','production_ha_dr_proven':False}

def kafka_settings(config):
    from confluent_kafka.admin import AdminClient,ConfigResource,ResourceType
    admin=AdminClient(config);metadata=admin.list_topics(timeout=15);out={}
    resources=[ConfigResource(ResourceType.TOPIC,t) for t in TOPICS]
    configs=admin.describe_configs(resources,request_timeout=15)
    for resource in resources:
        settings=configs[resource].result(20);topic=metadata.topics.get(resource.name)
        if topic is None or topic.error:raise Problem('HA preflight: topic metadata unavailable')
        out[resource.name]=dict(min_insync_replicas=int(settings['min.insync.replicas'].value),unclean_leader_election=settings['unclean.leader.election.enable'].value=='true',partitions=[dict(replicas=len(p.replicas),isr=len(p.isrs)) for p in topic.partitions.values()])
    return out

def from_environment(meta,ch,config):
    import os
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(meta.dsn).get('sslmode')!='verify-full':raise Problem('HA preflight requires PostgreSQL verify-full TLS')
    if not ch.url.startswith('https://'):raise Problem('HA preflight requires ClickHouse HTTPS')
    if config.get('security.protocol') not in ('SSL','SASL_SSL') or config.get('enable.ssl.certificate.verification',True) is not True or config.get('ssl.endpoint.identification.algorithm','https')!='https':raise Problem('HA preflight requires Kafka verified TLS')
    if os.environ.get('NOVA_ARCHIVE_MODE')!='s3-object-lock':raise Problem('HA preflight requires Object Lock archive mode')
    from ..retention import ObjectLockArchive
    ObjectLockArchive.from_environment()
    return check(meta,ch,kafka_settings(config))
