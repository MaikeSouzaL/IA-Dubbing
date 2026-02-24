import json
import subprocess
import sys
import time
import os.path

from config_loader import config
from logger import setup_logger, log_progress
from utils import load_json, save_json

logger = setup_logger(__name__)

try:
    from deep_translator import GoogleTranslator
except ImportError:
    logger.info("Instalando deep-translator...")
    subprocess.run([sys.executable, "-m", "pip", "install", "deep-translator"], check=True, encoding='utf-8', errors='replace')
    from deep_translator import GoogleTranslator

IN_ARQ = "transcricao.json"
OUT_ARQ = "transcricao_pt.json"

if not os.path.isfile(IN_ARQ):
    logger.error(f"{IN_ARQ} não encontrado.")
    sys.exit(1)

data = load_json(IN_ARQ)

target_lang = config.get("translation.target_language", "pt")
translator = GoogleTranslator(source='auto', target=target_lang)

data_pt = []
total = len(data)
retry_attempts = config.get("translation.retry_attempts", 3)
retry_delay = config.get("translation.retry_delay", 1.0)

for idx, chunk in enumerate(data, 1):
    # Progresso de 20 a 30%
    percent = 20.0 + (idx / total) * 10.0
    log_progress(logger, percent)

    texto = (chunk.get("transcript") or "").strip()
    logger.info(f"Traduzindo {idx}/{total}...")
    traducao = ""
    if texto:
        for tentativa in range(retry_attempts):
            try:
                traducao = translator.translate(texto)
                break
            except Exception as e:
                logger.warning(f"  Erro tentativa {tentativa+1}: {e}")
                time.sleep(retry_delay * (tentativa + 1))
        if not traducao:
            logger.error("  Falha definitiva, mantendo vazio.")
            
    novo_chunk = chunk.copy()
    novo_chunk["transcript_pt"] = traducao
    data_pt.append(novo_chunk)

log_progress(logger, 30.0)
save_json(data_pt, OUT_ARQ)
logger.info(f"✅ Tradução salva em {OUT_ARQ}")

if not data_pt or all(not c.get("transcript_pt") for c in data_pt):
    logger.warning("⚠️ Traduções vazias; verificando conectividade ou quota.")
else:
    logger.info("🔄 Iniciando extração de frases e tempos...")
    subprocess.run([sys.executable, "extrair_frases_pt.py"], check=False, encoding='utf-8', errors='replace')