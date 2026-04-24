import json
import re
import time
import subprocess
import sys
import os
import requests

from config_loader import config
from logger import setup_logger, log_progress
from utils import load_json, save_json
from job_manager import copy_artifact, mark_step

logger = setup_logger(__name__)

try:
    from deep_translator import GoogleTranslator
except ImportError:
    if config.get("app.offline_mode", False):
        GoogleTranslator = None
        logger.warning("deep-translator nao instalado; modo offline usara texto original.")
    else:
        subprocess.run([sys.executable, "-m", "pip", "install", "deep-translator"], check=True, encoding='utf-8', errors='replace')
        from deep_translator import GoogleTranslator

def split_sentences(transcript):
    # Divide o texto em frases usando pontuação comum (inclui o ponto hindi '।')
    frases = re.split(r'(?<=[.!?।])\s+', transcript)
    return [f.strip() for f in frases if f.strip()]

def alinhar_frases_palavras(words, max_duracao=12.0):
    if not words:
        return []
    frases = []
    acumuladas = []
    start_frase = None
    for w in words:
        wtxt = (w.get("word") or "").strip()
        if not wtxt:
            continue
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", w_start))
        if start_frase is None:
            start_frase = w_start
        acumuladas.append((wtxt, w_start, w_end))
        dur_atual = w_end - start_frase
        if wtxt[-1:] in ".!?।" or dur_atual >= max_duracao:
            texto = " ".join(x[0] for x in acumuladas)
            end_frase = acumuladas[-1][2]
            frases.append({"frase": texto, "start": start_frase, "end": end_frase, "slot_dur": end_frase - start_frase})
            acumuladas = []
            start_frase = None
    if acumuladas:
        texto = " ".join(x[0] for x in acumuladas)
        end_frase = acumuladas[-1][2]
        frases.append({"frase": texto, "start": start_frase, "end": end_frase, "slot_dur": end_frase - start_frase})
    return frases

def finalizar_com_virgula_se_ponto(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    closers = ['"', "'", '”', '’', '»', ')', ']', '}', '）', '」', '』']
    i = len(s) - 1
    # pula fechamentos/espacos no fim
    while i >= 0 and s[i] in closers + [' ', '\u00A0']:
        i -= 1
    if i < 0:
        return s
    # não altera reticências unicode
    if s[i] == '\u2026':
        return s
    # conta pontos consecutivos imediatamente antes do sufixo
    j = i
    dots = 0
    while j >= 0 and s[j] == '.':
        dots += 1
        j -= 1
    # troca apenas se for exatamente 1 ponto final
    if dots == 1:
        return s[:i] + ',' + s[i+1:]
    return s

# Carrega transcrição
try:
    data = load_json("transcricao.json")
except Exception as e:
    logger.error(f"Erro ao ler transcricao.json: {e}")
    sys.exit(1)

# Pré-segmenta todas as frases para calcular total
segmentos_por_chunk = []
total = 0
max_dur = config.get("audio.segmentation.max_phrase_duration", 10.0)

for chunk in data:
    words = chunk.get("words", [])
    segs = alinhar_frases_palavras(words, max_duracao=max_dur)
    segmentos_por_chunk.append(segs)
    total += len(segs)

target_lang = config.get("translation.target_language", "pt")
translator = GoogleTranslator(source='auto', target=target_lang) if GoogleTranslator is not None else None
frases_pt = []
cont = 1
translation_cache = {}
offline_mode = config.get("app.offline_mode", False)
offline_strategy = config.get("translation.offline_strategy", "original")

def traduzir_contextual(texto, target_lang, slot_dur=None):
    provider = config.get("translation.provider", "googletranslator")
    if provider != "openai":
        return translator.translate(texto)
    api_key = os.environ.get("OPENAI_API_KEY") or config.get("translation.openai_api_key", None)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY nao configurada para traducao OpenAI.")
    model = config.get("translation.openai_model", "gpt-4o-mini")
    timing = ""
    if config.get("translation.preserve_timing_style", True) and slot_dur:
        timing = f" Mantenha a fala curta para caber em aproximadamente {slot_dur:.1f} segundos."
    prompt = (
        f"Traduza para {target_lang} mantendo sentido, naturalidade oral e estilo de fala."
        f"{timing} Responda somente com a traducao.\n\nTexto: {texto}"
    )
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        },
        timeout=120,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI traducao falhou ({resp.status_code}): {resp.text[:500]}")
    return resp.json()["choices"][0]["message"]["content"].strip()

retry_attempts = config.get("translation.retry_attempts", 3)
retry_delay = config.get("translation.retry_delay", 1.0)

total_chunks = len(segmentos_por_chunk)

for idx, segs in enumerate(segmentos_por_chunk):
    # Progresso de 30 a 35%
    percent = 30.0 + (idx / total_chunks) * 5.0
    log_progress(logger, percent)

    for frase_info in segs:
        origem = frase_info["frase"]
        logger.info(f"Traduzindo frase {cont}/{total}: {origem[:60]}...")
        frase_pt_text = ""
        if origem:
            if offline_mode:
                frase_pt_text = origem if offline_strategy == "original" else ""
            elif origem in translation_cache:
                frase_pt_text = translation_cache[origem]
            else:
                # Traduz cada frase individualmente com tentativas e pausa
                for tentativa in range(retry_attempts):
                    try:
                        frase_pt_text = traduzir_contextual(origem, target_lang, frase_info.get("slot_dur"))
                        break
                    except Exception as e:
                        logger.warning(f"  Erro tentativa {tentativa+1}: {e}")
                        time.sleep(retry_delay * (tentativa + 1))
                translation_cache[origem] = frase_pt_text or ""
        
        # aplica vírgula somente se terminar com ponto
        if frase_pt_text:
            frase_pt_text = finalizar_com_virgula_se_ponto(frase_pt_text)

        frases_pt.append({
            "frase_pt": frase_pt_text or "",
            "start": frase_info["start"],
            "end": frase_info["end"],
            "slot_dur": frase_info["slot_dur"],
            "frase_original": origem
        })
        cont += 1

log_progress(logger, 35.0)
save_json(frases_pt, "frases_pt.json")
copy_artifact("frases_pt.json", "frases_pt.json")
mark_step("phrases", "done", count=len(frases_pt))
logger.info(f"✅ frases_pt.json gerado com {len(frases_pt)} frases.")

# Fallback se vazio
if not frases_pt:
    logger.warning("⚠️ Lista vazia; tentando fallback em transcricao_pt.json...")
    if os.path.isfile("transcricao_pt.json"):
        try:
            data_pt = load_json("transcricao_pt.json")
            fallback = []
            for chunk in data_pt:
                frase_pt_text = (chunk.get("transcript_pt") or "").strip()
                fallback.append({
                    "frase_pt": frase_pt_text,
                    "start": chunk.get("start", 0.0),
                    "end": chunk.get("end", 0.0),
                    "frase_original": chunk.get("transcript", "")
                })
            save_json(fallback, "frases_pt.json")
            logger.info("✅ Fallback aplicado.")
        except Exception as e:
            logger.error(f"Erro no fallback: {e}")

logger.info("🔄 Iniciando dublagem...")
mark_step("tts", "running")
ret = subprocess.run([sys.executable, "dublar_frases_pt.py"], check=False, encoding='utf-8', errors='replace')
if ret.returncode != 0:
    mark_step("tts", "error", code=ret.returncode)
    logger.error(f"❌ dublar_frases_pt.py falhou (código {ret.returncode}).")
    sys.exit(ret.returncode)
