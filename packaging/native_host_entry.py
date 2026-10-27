import sys
from pathlib import Path
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'vendor'))
sys.path.insert(0, str(root))
from linuxdm.native_host import main
main()
