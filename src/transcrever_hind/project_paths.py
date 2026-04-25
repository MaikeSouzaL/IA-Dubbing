import os
from pathlib import Path
from typing import Union

from config_loader import config


def _find_project_root() -> Path:
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for candidate in (start, *start.parents):
            if (candidate / "config.yaml").is_file() and (candidate / ".venv").exists():
                return candidate
    return Path.cwd().resolve()


ROOT = _find_project_root()


def configure_local_tools() -> None:
    ffmpeg_bin = ROOT / "tools" / "ffmpeg" / "bin"
    if ffmpeg_bin.is_dir():
        current_path = os.environ.get("PATH", "")
        ffmpeg_text = str(ffmpeg_bin)
        path_parts = [p.rstrip("\\/") for p in current_path.split(os.pathsep) if p]
        if ffmpeg_text.rstrip("\\/") not in path_parts:
            os.environ["PATH"] = f"{ffmpeg_text}{os.pathsep}{current_path}"


configure_local_tools()


def _configured_dir(key: str, default: str) -> Path:
    value = config.get(key, default)
    path = Path(str(value))
    if not path.is_absolute():
        path = ROOT / path
    return path


def inputs_dir() -> Path:
    return _configured_dir("paths.inputs_dir", "data/inputs")


def outputs_dir() -> Path:
    return _configured_dir("paths.outputs_dir", "data/outputs")


def work_dir() -> Path:
    return _configured_dir("paths.work_dir", "data/work")


def temp_dir() -> Path:
    return _configured_dir("paths.temp_dir", "data/temp")


def reports_dir() -> Path:
    return _configured_dir("paths.reports_dir", "data/reports")


def cache_dir() -> Path:
    return _configured_dir("paths.cache_dir", "data/cache")


def jobs_dir() -> Path:
    return _configured_dir("paths.jobs_dir", "data/jobs")


def ensure_project_dirs() -> None:
    for directory in (
        inputs_dir(),
        outputs_dir(),
        work_dir(),
        temp_dir(),
        reports_dir(),
        cache_dir(),
        jobs_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)


def input_file(name: Union[str, Path]) -> Path:
    return inputs_dir() / Path(name)


def output_file(name: Union[str, Path]) -> Path:
    return outputs_dir() / Path(name)


def work_file(name: Union[str, Path]) -> Path:
    return work_dir() / Path(name)


def temp_file(name: Union[str, Path]) -> Path:
    return temp_dir() / Path(name)


def report_file(name: Union[str, Path]) -> Path:
    return reports_dir() / Path(name)


def cache_file(name: Union[str, Path]) -> Path:
    return cache_dir() / Path(name)


def pipeline_file(name: Union[str, Path]) -> Path:
    """Prefer the organized work file, but keep compatibility with root files."""
    organized = work_file(name)
    if organized.exists():
        return organized
    legacy = ROOT / Path(name)
    return legacy


def video_original_file() -> Path:
    return work_file("video_original.txt")
