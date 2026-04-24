import os
from pathlib import Path
from typing import Dict


ENV_FILE = Path(__file__).parent / ".env"


def load_env_file(path: Path = ENV_FILE) -> Dict[str, str]:
    values = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
        os.environ.setdefault(key, value)
    return values


def save_env_value(key: str, value: str, path: Path = ENV_FILE) -> None:
    values = load_env_file(path)
    if value:
        values[key] = value
    elif key in values:
        del values[key]
    lines = [f"{k}={v}" for k, v in sorted(values.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    if value:
        os.environ[key] = value
    elif key in os.environ:
        del os.environ[key]
