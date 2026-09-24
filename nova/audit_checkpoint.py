"""Offline local audit verification and checkpoint creation; preserve checkpoints externally."""
import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from .core import identifier
from .enterprise import verify_audit
from .operations import readonly

def main():
    p=argparse.ArgumentParser(description='Verify linked local audit history and emit a checkpoint')
    p.add_argument('--db',default='data/nova.db');p.add_argument('--tenant',required=True);p.add_argument('--anchor');p.add_argument('--output')
    a=p.parse_args();identifier(a.tenant,'tenant')
    anchor=json.loads(Path(a.anchor).read_text()) if a.anchor else None
    with closing(readonly(a.db)) as c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN')
        checkpoint=verify_audit(c,a.tenant,anchor=anchor,max_records=10000000)
    text=json.dumps(checkpoint,indent=2)+'\n'
    if a.output:
        fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
    else:print(text,end='')

if __name__=='__main__':main()
