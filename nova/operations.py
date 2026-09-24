"""Local diagnostics and online SQLite snapshots; restores never overwrite a database."""
import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path
from .core import Problem,canonical

def readonly(path):
    path=Path(path).resolve()
    if not path.is_file():raise Problem('database does not exist')
    return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)

def doctor(path):
    with closing(readonly(path)) as c:
        integrity=c.execute('PRAGMA quick_check').fetchone()[0]
        counts={table:c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('raw_events','normalized','quarantine','alerts')}
        pending=c.execute("SELECT COUNT(*) FROM raw_events r WHERE NOT EXISTS (SELECT 1 FROM processed p WHERE p.consumer='normalizer' AND p.tenant=r.tenant AND p.event_id=r.event_id)").fetchone()[0]
    return {'integrity':integrity,'counts':counts,'normalizer_pending':pending,'guidance':(['Stop writes and restore a verified snapshot to a new path.'] if integrity!='ok' else [])+(['Inspect worker health and integration activation; do not delete the journal.'] if pending else [])+(['Inspect quarantine reasons; activate the correct parser before bounded replay.'] if counts['quarantine'] else [])}

def backup(db,output):
    output=Path(output)
    if output.exists():raise Problem('backup destination already exists')
    output.mkdir(mode=0o700,parents=True)
    target=output/'nova.db'
    source=readonly(db)
    try:
        destination=sqlite3.connect(target)
        try:source.backup(destination,pages=256,sleep=.01)
        finally:destination.close()
    finally:source.close()
    os.chmod(target,0o600)
    with closing(readonly(target)) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise Problem('snapshot integrity failed')
    with target.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    manifest={'format':'nova.sqlite-snapshot.v1','sha256':digest,'created':time.time(),'database_bytes':target.stat().st_size,'includes':'SQLite event and control state only; credentials, packages and archives must be backed up separately'}
    (output/'manifest.json').write_text(canonical(manifest)+'\n')
    return manifest

def restore(snapshot,output):
    snapshot=Path(snapshot);output=Path(output)
    manifest=json.loads((snapshot/'manifest.json').read_text())
    if manifest.get('format')!='nova.sqlite-snapshot.v1':raise Problem('unsupported snapshot format')
    if output.exists():raise Problem('restore refuses to overwrite an existing database')
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=output.parent,prefix='nova-restore-')
    try:
        digest=hashlib.sha256()
        with os.fdopen(fd,'wb') as f, (snapshot/'nova.db').open('rb') as source:
            while True:
                chunk=source.read(1048576)
                if not chunk:break
                digest.update(chunk);f.write(chunk)
            f.flush();os.fsync(f.fileno())
        if digest.hexdigest()!=manifest['sha256']:raise Problem('snapshot checksum mismatch')
        with closing(readonly(temp)) as c:
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise Problem('snapshot integrity check failed')
        # Hard link is atomic and fails if a racing process created output.
        os.link(temp,output)
        directory=os.open(output.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:os.unlink(temp)
    return {'restored':str(output),'sha256':manifest['sha256']}

def main():
    os.umask(0o077)
    p=argparse.ArgumentParser(description='Nova local diagnostics and snapshot recovery')
    p.add_argument('command',choices=['doctor','backup','restore']);p.add_argument('--db',default='data/nova.db');p.add_argument('--output');p.add_argument('--snapshot')
    a=p.parse_args()
    if a.command!='doctor' and not a.output:p.error('--output required')
    if a.command=='restore' and not a.snapshot:p.error('--snapshot required')
    print(json.dumps(doctor(a.db) if a.command=='doctor' else backup(a.db,a.output) if a.command=='backup' else restore(a.snapshot,a.output),indent=2))

if __name__=='__main__':main()
