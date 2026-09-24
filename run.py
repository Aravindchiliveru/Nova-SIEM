"""One-command local launch: python3 run.py"""
import sys
from pathlib import Path
from nova.server import initialize,main
if __name__=='__main__':
    root=Path(__file__).resolve().parent
    data=root/'data'
    if not (data/'credentials.json').exists(): initialize(data)
    sys.argv=[sys.argv[0],'serve','--data',str(data)]+sys.argv[1:]
    main()
