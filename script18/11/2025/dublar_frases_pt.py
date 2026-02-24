import os
import json
import re
import sys
import time
from pydub import AudioSegment
# >>> ADIÇÃO: garantir que o .models.json exista para a cópia local do TTS
import urllib.request

def _ensure_models_json_local_tts():
    pkg_dir = os.path.join(os.path.dirname(__file__), "TTS", "TTS")
    os.makedirs(pkg_dir, exist_ok=True)
    models_path = os.path.join(pkg_dir, ".models.json")
    if not os.path.isfile(models_path):
        try:
            print("⬇️ Baixando TTS/.models.json para a instalação local...")
            url = "https://raw.githubusercontent.com/coqui-ai/TTS/main/TTS/.models.json"
            urllib.request.urlretrieve(url, models_path)
        except Exception as e:
            print(f"⚠️ Falha ao baixar .models.json: {e}")
    return models_path

_ensure_models_json_local_tts()
# <<< FIM ADIÇÃO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "TTS"))
from TTS.api import TTS
import subprocess
import torch

# Importa o deep-translator se for necessário gerar frases_pt
try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

def split_sentences(transcript):
    frases = re.split(r'(?<=[.!?।])\s+', transcript)
    return [f.strip() for f in frases if f.strip()]

def alinhar_frases_palavras(frases, words):
    frases_com_tempo = []
    idx = 0
    for frase in frases:
        frase_palavras = frase.split()
        if not frase_palavras:
            continue
        start = words[idx]["start"]
        end = words[min(idx + len(frase_palavras) - 1, len(words)-1)]["end"]
        frases_com_tempo.append({
            "frase": frase,
            "start": start,
            "end": end
        })
        idx += len(frase_palavras)
    return frases_com_tempo

def gerar_frases_pt(transcricao_json, frases_pt_json):
    if GoogleTranslator is None:
        raise RuntimeError("deep-translator não instalado. Rode: pip install deep-translator")
    with open(transcricao_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    frases_pt = []
    for chunk in data:
        transcript = chunk.get("transcript", "") or ""
        words = chunk.get("words", []) or []
        frases = split_sentences(transcript)
        frases_tempo = alinhar_frases_palavras(frases, words) if words else []
        for frase_info in frases_tempo:
            frase_hi = frase_info["frase"]
            # Traduz para português (auto-detecta origem)
            try:
                frase_pt = GoogleTranslator(source='auto', target='pt').translate(frase_hi)
            except Exception:
                frase_pt = frase_hi  # fallback: mantém original
            frases_pt.append({
                "frase_pt": frase_pt,
                "start": frase_info["start"],
                "end": frase_info["end"]
            })
    with open(frases_pt_json, "w", encoding="utf-8") as f:
        json.dump(frases_pt, f, ensure_ascii=False, indent=2)
    print(f"✅ Frases em português salvas em {frases_pt_json}")

def dublar_frases(frases_pt_json, vocals_path, saida_dir):
    with open(frases_pt_json, "r", encoding="utf-8") as f:
        frases = json.load(f)

    use_gpu = torch.cuda.is_available()
    print(f"Inicializando XTTS v2 (gpu={use_gpu})...")
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False, gpu=use_gpu)

    os.makedirs(saida_dir, exist_ok=True)
    for i, frase in enumerate(frases):
        texto = (frase.get("frase_pt") or "").strip()
        if not texto:
            continue
        # Remoção opcional de pontuação final para evitar pausas longas
        if texto and texto[-1] in ".!?।":
            texto = texto[:-1].strip()

        audio_path = os.path.join(saida_dir, f"frase_{i:03d}.wav")
        print(f"[TTS] {i+1}/{len(frases)} -> '{texto[:60]}...'")

        try:
            tts.tts_to_file(
                text=texto,
                file_path=audio_path,
                speaker_wav=vocals_path if os.path.isfile(vocals_path) else None,
                language="pt"
            )
            # Limpa cache de GPU (se houver) para reduzir OOM
            if use_gpu:
                torch.cuda.empty_cache()
        except TypeError:
            # Algumas versões exigem não passar speaker_wav=None
            tts.tts_to_file(
                text=texto,
                file_path=audio_path,
                language="pt"
            )
        except Exception as e:
            print(f"❌ Erro ao dublar frase {i}: {e}")

        # Pós-processamento simples: evitar WAVs muito longos em relação ao slot
        try:
            dur_slot = max(0.0, float(frase.get("end", 0)) - float(frase.get("start", 0)))
            if dur_slot > 0:
                seg = AudioSegment.from_file(audio_path)
                max_ms = int((dur_slot + 0.2) * 1000)  # 200 ms de folga
                if len(seg) > max_ms:
                    seg = seg[:max_ms]
                    seg.export(audio_path, format="wav")
        except Exception:
            pass

        time.sleep(0.03)

    print(f"Todos os áudios foram gerados na pasta {saida_dir}.")

if __name__ == "__main__":
    # Carrega o nome do vídeo salvo na primeira etapa
    with open("video_original.txt", "r", encoding="utf-8") as f_video:
        video = f_video.read().strip()
    base = os.path.splitext(os.path.basename(video))[0]
    vocals = os.path.join("separated", "htdemucs", base, "vocals.wav")
    transcricao = "transcricao.json"
    frases_pt = "frases_pt.json"
    saida_audios = "audios_frases_pt"

    if not os.path.isfile(frases_pt):
        gerar_frases_pt(transcricao, frases_pt)

    if not os.path.isfile(vocals):
        print(f"⚠️ vocals.wav não encontrado em {vocals}. Gerando TTS sem clonagem de voz.")
    else:
        print(f"🎤 Usando vocals: {vocals}")

    dublar_frases(frases_pt, vocals, saida_audios)

    print("🔄 Iniciando sincronização e junção das frases...")
    subprocess.run([sys.executable, "sincronizar_e_juntar.py"])
    print("🔄 Iniciando dublagem das frases...")
    subprocess.run([sys.executable, "dublar_frases_pt.py"], check=True, cwd=os.path.dirname(os.path.abspath(__file__)))