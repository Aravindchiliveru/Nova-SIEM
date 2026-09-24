"""Development evidence archive; shared filesystem, not WORM/object storage."""
import hashlib
import os
import tempfile
from pathlib import Path
from ..core import canonical
from .contracts import validate_raw

class Archive:
    def __init__(self,root):self.root=Path(root)
    def write(self,rows):
        for raw in rows:
            validate_raw(raw)
            data=canonical(raw).encode()
            digest=hashlib.sha256(data).hexdigest()
            # Tenant may include punctuation; hash prevents filesystem path semantics.
            tenant=hashlib.sha256(raw['tenant'].encode()).hexdigest()
            directory=self.root/tenant/raw['event_id'][:2]/raw['event_id']
            directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            target=directory/(digest+'.json')
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise RuntimeError('archive integrity mismatch')
                continue
            fd,tmp=tempfile.mkstemp(prefix='.pending-',dir=directory)
            try:
                with os.fdopen(fd,'wb') as f:
                    f.write(data);f.flush();os.fsync(f.fileno())
                os.replace(tmp,target)
                # Persist directory entries up to root before acknowledging.
                current=directory
                while True:
                    dirfd=os.open(current,os.O_RDONLY|os.O_DIRECTORY)
                    try:os.fsync(dirfd)
                    finally:os.close(dirfd)
                    if current==self.root:break
                    current=current.parent
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
