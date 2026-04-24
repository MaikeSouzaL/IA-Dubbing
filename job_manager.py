import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from logger import setup_logger

logger = setup_logger(__name__)


ROOT = Path(__file__).parent.resolve()
JOBS_DIR = ROOT / "jobs"
CURRENT_JOB_FILE = ROOT / "current_job.json"


def _safe_slug(value: str, max_len: int = 80) -> str:
    value = value or "job"
    value = re.sub(r"https?://", "", value, flags=re.I)
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = value.strip("._-") or "job"
    return value[:max_len]


def create_job(input_ref: str, input_mode: str = "file") -> Dict[str, Any]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _safe_slug(Path(input_ref).stem if input_mode == "file" else input_ref)
    job_dir = JOBS_DIR / f"{stamp}_{input_mode}_{slug}"
    job_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "id": job_dir.name,
        "job_dir": str(job_dir),
        "input_ref": input_ref,
        "input_mode": input_mode,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "steps": {},
        "artifacts": {},
    }
    save_job_state(state)
    return state


def load_current_job() -> Optional[Dict[str, Any]]:
    if not CURRENT_JOB_FILE.is_file():
        return None
    try:
        return json.loads(CURRENT_JOB_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Nao foi possivel ler job atual: {e}")
        return None


def save_job_state(state: Dict[str, Any]) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    job_dir = Path(state["job_dir"])
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    CURRENT_JOB_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_step(step: str, status: str, **extra: Any) -> None:
    state = load_current_job()
    if not state:
        return
    state.setdefault("steps", {})[step] = {
        "status": status,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **extra,
    }
    save_job_state(state)


def add_artifact(name: str, path: str) -> None:
    state = load_current_job()
    if not state:
        return
    state.setdefault("artifacts", {})[name] = os.path.abspath(path)
    save_job_state(state)


def copy_artifact(path: str, name: Optional[str] = None) -> Optional[str]:
    state = load_current_job()
    if not state or not path or not os.path.exists(path):
        return None
    job_dir = Path(state["job_dir"])
    target = job_dir / (name or os.path.basename(path))
    try:
        if Path(path).resolve() != target.resolve():
            shutil.copy2(path, target)
        add_artifact(name or os.path.basename(path), str(target))
        return str(target)
    except Exception as e:
        logger.warning(f"Nao foi possivel copiar artefato para job: {path} -> {e}")
        return None


def infer_resume_step() -> str:
    """Retorna a etapa mais segura para retomar usando arquivos atuais."""
    if os.path.isfile(ROOT / "audio_final_mix.wav"):
        return "render"
    if os.path.isfile(ROOT / "frases_pt.json"):
        try:
            data = json.loads((ROOT / "frases_pt.json").read_text(encoding="utf-8"))
            total = len(data) if isinstance(data, list) else 0
            done = 0
            audios_dir = ROOT / "audios_frases_pt"
            if audios_dir.is_dir():
                done = len([x for x in audios_dir.iterdir() if x.name.startswith("frase_") and x.suffix == ".wav"])
            if total > 0 and done >= total:
                return "sync"
            return "tts"
        except Exception:
            return "tts"
    if os.path.isfile(ROOT / "transcricao.json"):
        return "translate"
    return "full"
