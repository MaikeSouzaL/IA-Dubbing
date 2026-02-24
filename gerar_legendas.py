import os
import sys
from datetime import timedelta

from config_loader import config
from logger import setup_logger
from utils import load_json

logger = setup_logger(__name__)

def format_srt_time(seconds: float) -> str:
    """
    Converte segundos para formato SRT: HH:MM:SS,mmm
    Exemplo: 65.5 -> 00:01:05,500
    """
    td = timedelta(seconds=seconds)
    hours = int(td.total_seconds() // 3600)
    minutes = int((td.total_seconds() % 3600) // 60)
    secs = int(td.total_seconds() % 60)
    millis = int((td.total_seconds() % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def gerar_legenda_srt(frases_json: str, output_srt: str, usar_traducao: bool = True):
    """
    Gera arquivo de legenda .srt a partir do frases_pt.json
    
    Args:
        frases_json: Caminho para frases_pt.json
        output_srt: Caminho de saída do arquivo .srt
        usar_traducao: Se True, usa frase_pt; se False, usa frase_original
    """
    if not os.path.isfile(frases_json):
        logger.error(f"Arquivo {frases_json} não encontrado.")
        return False
    
    frases = load_json(frases_json)
    
    if not frases:
        logger.warning("Nenhuma frase encontrada para gerar legenda.")
        return False
    
    with open(output_srt, 'w', encoding='utf-8') as f:
        for i, frase in enumerate(frases, 1):
            # Pega o texto apropriado
            if usar_traducao:
                texto = (frase.get("frase_pt") or "").strip()
            else:
                texto = (frase.get("frase_original") or "").strip()
            
            if not texto:
                continue
            
            # Pega os timestamps
            start = float(frase.get("start", 0.0))
            end = float(frase.get("end", start + 2.0))  # Fallback de 2s se não tiver end
            
            # Formata no padrão SRT
            f.write(f"{i}\n")
            f.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
            f.write(f"{texto}\n")
            f.write("\n")
    
    logger.info(f"✅ Legenda gerada: {output_srt} ({len(frases)} frases)")
    return True

if __name__ == "__main__":
    # Lê o nome do vídeo original
    try:
        with open("video_original.txt", "r", encoding="utf-8") as f:
            video = f.read().strip()
    except Exception as e:
        logger.error(f"Erro ao ler video_original.txt: {e}")
        sys.exit(1)
    
    base = os.path.splitext(os.path.basename(video))[0]
    frases_json = "frases_pt.json"
    
    # Gera legendas em português (traduzido)
    srt_pt = f"{base}_pt.srt"
    if gerar_legenda_srt(frases_json, srt_pt, usar_traducao=True):
        logger.info(f"📝 Legenda PT: {srt_pt}")
    
    # Gera legendas no idioma original
    srt_original = f"{base}_original.srt"
    if gerar_legenda_srt(frases_json, srt_original, usar_traducao=False):
        logger.info(f"📝 Legenda Original: {srt_original}")
    
    logger.info("✅ Geração de legendas concluída!")
