"""Compile-check a bounded local Sigma corpus without installing or enabling rules."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nova.sigma import compile_rule,load_yaml
from nova.core import canonical

def inspect(directory,binding):
    root=Path(directory).resolve()
    if not root.is_dir():raise ValueError('corpus directory required')
    paths=sorted(p for p in root.rglob('*') if p.suffix in ('.yaml','.yml') and p.is_file())
    if not 1<=len(paths)<=10000:raise ValueError('corpus requires 1..10000 YAML files')
    results=[]
    for path in paths:
        item={'path':str(path.relative_to(root))}
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('external or symbolic rule path rejected')
            if path.stat().st_size>65536:raise ValueError('rule exceeds 64 KiB')
            item['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            compiled=compile_rule(load_yaml(path),binding)
            item.update(status='compiled',rule_id=compiled['id'],compiled_sha256=hashlib.sha256(canonical(compiled).encode()).hexdigest())
        except Exception as exc:item.update(status='rejected',reason=str(exc)[:300],error_type=type(exc).__name__)
        results.append(item)
    accepted=sum(x['status']=='compiled' for x in results)
    return dict(scope='Compiler acceptance only; not semantic corpus parity or conformance certification',binding_sha256=hashlib.sha256(canonical(binding).encode()).hexdigest(),total=len(results),compiled=accepted,rejected=len(results)-accepted,rules=results)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory');p.add_argument('--binding',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=inspect(a.directory,json.loads(Path(a.binding).read_text()))
    with open(a.output,'x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='rules'},indent=2));return 0 if result['rejected']==0 else 2
if __name__=='__main__':raise SystemExit(main())
