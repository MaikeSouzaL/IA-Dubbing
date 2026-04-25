from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent.parent
IMPL = ROOT / "src" / "transcrever_hind"
sys.path.insert(0, str(IMPL))
runpy.run_path(str(IMPL / "validar_etapas.py"), run_name="__main__")

