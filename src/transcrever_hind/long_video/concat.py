import os
from pathlib import Path
from .utils import safe_run

def concat_mp4_parts(dubbed_parts: list[str], output_path: str):
    if not dubbed_parts:
        raise ValueError("Lista de partes dubladas vazia.")
    # arquivo de lista para o concat demuxer
    list_file = "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in dubbed_parts:
            # usar caminhos absolutos e -safe 0
            f.write(f"file '{os.path.abspath(p)}'\n")

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-safe", "0",
        "-f", "concat", "-i", list_file,
        "-c", "copy",
        output_path
    ]
    print("FFmpeg concat:", " ".join(cmd))
    r = safe_run(cmd, check=False)
    try:
        os.remove(list_file)
    except Exception:
        pass
    return r.returncode == 0 and os.path.isfile(output_path)