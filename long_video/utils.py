import os
import sys
import subprocess

def safe_run(cmd, check=False, capture=False, cwd=None, input_text=None):
    return subprocess.run(
        cmd,
        check=check,
        cwd=cwd,
        input=input_text if input_text is not None else None,
        text=True,
        stdout=(subprocess.PIPE if capture else None),
        stderr=(subprocess.PIPE if capture else None),
    )

def ffprobe_duration(path: str):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        return float(r.stdout.strip())
    except Exception:
        return None

def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path