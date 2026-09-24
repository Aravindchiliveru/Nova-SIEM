from .core import Problem

def valid_id(value):
    try:
        if isinstance(value,bool):raise ValueError()
        n=int(value)
        if n<1 or str(n)!=str(value):raise ValueError()
        return n
    except (ValueError,TypeError,OverflowError):raise Problem('invalid case id')

def validate_update(body):
    if not isinstance(body,dict) or set(body)-{'id','status','note'}:raise Problem('invalid case update fields')
    n=valid_id(body.get('id'));status=body.get('status');note=body.get('note')
    if status is not None and status not in ('open','investigating','resolved','closed'):raise Problem('invalid case status')
    if note is not None and (not isinstance(note,str) or not 1<=len(note.strip())<=8192):raise Problem('note must contain 1..8192 characters')
    if status is None and note is None:raise Problem('status or note required')
    return n,status,note
