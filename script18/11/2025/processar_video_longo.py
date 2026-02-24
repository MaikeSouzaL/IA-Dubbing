# filepath: d:\Transcrever_hind\processar_video_longo.py
import os
import sys
import subprocess
from pathlib import Path
from glob import glob
import unicodedata

# Utils locais
from long_video.utils import ffprobe_duration, safe_run
from long_video.split import split_video_into_parts

MINUTES_LIMIT = 15  # limite para decidir dividir

def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")

def normalize_ascii(s: str) -> str:
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')

def baixar_video(url: str) -> str:
    print("⏬ Baixando vídeo do YouTube...")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo+bestaudio/best",
        "-o", "%(title)s.%(ext)s",
        url
    ]
    safe_run(cmd, check=True)
    # Aceita várias extensões (yt-dlp pode gerar .webm, .mp4, etc.)
    candidates = []
    for pat in ("*.mp4", "*.webm", "*.mkv", "*.mov"):
        candidates += glob(pat)
    if not candidates:
        raise RuntimeError("Falha ao baixar o vídeo (nenhum arquivo de vídeo encontrado).")
    newest = max(candidates, key=os.path.getmtime)
    return newest

def concat_parts_ffmpeg(parts, out_file, workdir):
    list_file = os.path.join(workdir, "concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        out_file
    ]
    print("🔗 Concatenando partes dubladas...")
    subprocess.run(cmd, check=True)
    try:
        os.remove(list_file)
    except Exception:
        pass

def main():
    ROOT = os.path.dirname(os.path.abspath(__file__))
    print("=== Dublagem para Vídeos Longos ===")
    print("1 - Inserir URL do YouTube")
    print("2 - Inserir caminho de arquivo local")
    op = input("Opção (1 ou 2): ").strip()

    if op == "1":
        url = input("Cole a URL do vídeo do YouTube: ").strip()
        video_path = baixar_video(url)
    elif op == "2":
        video_path = input("Caminho do arquivo (ex.: C:\\videos\\meu_video.mp4): ").strip().strip('"')
        if not os.path.isfile(video_path):
            print(f"❌ Arquivo não encontrado: {video_path}")
            sys.exit(1)
    else:
        print("Opção inválida.")
        sys.exit(1)

    video_path = os.path.abspath(video_path)
    ascii_video_path = normalize_ascii(video_path)
    if video_path != ascii_video_path:
        try:
            if not os.path.exists(ascii_video_path):
                os.rename(video_path, ascii_video_path)
                video_path = ascii_video_path
            else:
                # Evita colisão de nome
                stem = Path(ascii_video_path).stem
                ext = Path(ascii_video_path).suffix
                alt = os.path.join(os.path.dirname(ascii_video_path), f"{stem}_ascii{ext}")
                os.rename(video_path, alt)
                video_path = alt
        except Exception as e:
            print(f"⚠️ Não foi possível renomear para ASCII: {e}")
            sys.exit(1)

    print(f"✅ Vídeo selecionado: {video_path}")
    dur = ffprobe_duration(video_path) or 0
    base = Path(video_path).stem

    if dur <= MINUTES_LIMIT * 60:
        print("▶️ Vídeo com 15 min ou menos. Chamando pipeline padrão...")
        stdin_data = f"2\n{video_path}\n"
        res = subprocess.run(
            [sys.executable, "transcrever.py"],
            input=stdin_data,
            text=True,
            cwd=ROOT,
            encoding="utf-8"  # garante UTF-8 no stdin
        )
        sys.exit(res.returncode)
    # Vídeo longo
    print(f"📐 Vídeo longo detectado ({dur/60:.1f} min). Dividindo em partes por pausas (sem cortar falas)...")
    parts = split_video_into_parts(video_path, ROOT)  # salvar no raiz
    if not parts:
        print("❌ Não foi possível dividir o vídeo em partes.")
        sys.exit(1)
    print(f"🧩 {len(parts)} partes geradas.")

    dubbed_parts = []
    for idx, part in enumerate(parts, 1):
        print(f"\n🎬 Dublando parte {idx}/{len(parts)}: {part}")
        stdin_data = f"2\n{os.path.abspath(part)}\n"
        res = subprocess.run(
            [sys.executable, "transcrever.py"],
            input=stdin_data,
            text=True,
            cwd=ROOT,
            encoding="utf-8"
        )
        if res.returncode != 0:
            print(f"❌ Falha ao dublar a parte {part}.")
            sys.exit(res.returncode)

        stem = Path(part).stem
        dubbed = os.path.join(ROOT, f"{stem}_dublado.mp4")
        if not os.path.isfile(dubbed) or os.path.getsize(dubbed) == 0:
            print(f"❌ Parte dublada não encontrada: {dubbed}")
            sys.exit(1)
        print(f"✅ Parte dublada: {dubbed}")
        dubbed_parts.append(dubbed)

    out_final = os.path.join(ROOT, f"{base}_dublado.mp4")
    concat_parts_ffmpeg(dubbed_parts, out_final, ROOT)

    if os.path.isfile(out_final) and os.path.getsize(out_final) > 0:
        print(f"✅ Vídeo final dublado: {out_final}")
    else:
        print("⚠️ Falha na concatenação do vídeo final.")
        sys.exit(1)

if __name__ == "__main__":
    main()