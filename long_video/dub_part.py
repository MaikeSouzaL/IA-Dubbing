import os
import sys
import shutil
from pathlib import Path
from .utils import safe_run

def dublar_parte_com_pipeline(part_path: str, parts_dir: str) -> str:
    # Alimenta stdin: opção 2 + caminho do segmento
    stdin_data = f"2\n{os.path.abspath(part_path)}\n"
    print("▶️ Executando pipeline padrão para a parte (transcrever.py)...")
    res = safe_run([sys.executable, "transcrever.py"], check=False, input_text=stdin_data)
    if res.returncode != 0:
        print("⚠️ transcrever.py retornou erro. Saída (parcial):")
        print((res.stdout or "") + "\n" + (res.stderr or ""))
        return ""

    # Após pipeline, localizar o arquivo dublado
    stem = Path(part_path).stem
    esperado = f"{stem}_dublado.mp4"
    if os.path.isfile(esperado):
        # mover para a pasta das partes dubladas
        dest = os.path.join(parts_dir, esperado)
        try:
            if os.path.isfile(dest):
                os.remove(dest)
            shutil.move(esperado, dest)
            return dest
        except Exception:
            # fallback: copia
            shutil.copy2(esperado, dest)
            return dest

    # fallback: tentar localizar qualquer *_dublado.mp4 mais recente
    candidatos = sorted(Path(".").glob("*_dublado.mp4"), key=os.path.getmtime)
    if candidatos:
        src = str(candidatos[-1])
        dest = os.path.join(parts_dir, esperado)
        try:
            if os.path.isfile(dest):
                os.remove(dest)
            shutil.move(src, dest)
        except Exception:
            shutil.copy2(src, dest)
        return dest

    print("❌ Não foi encontrado o arquivo dublado da parte.")
    return ""