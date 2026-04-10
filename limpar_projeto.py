import os
import glob
import shutil
from logger import setup_logger
from config_loader import config
from utils import safe_remove

logger = setup_logger(__name__)

def limpar():
    """
    Limpeza COMPLETA do projeto.
    Remove TUDO exceto o vídeo dublado final.
    
    Arquivos removidos:
    - Vídeo original
    - Pasta separated/ (stems do Demucs)
    - Todos os JSONs de transcrição/tradução
    - Todos os áudios temporários
    - Chunks de voz (vocals_*.wav)
    - Diretórios de trabalho
    """
    logger.info("🧹 Iniciando limpeza COMPLETA do projeto...")
    logger.info("⚠️  Removendo TUDO exceto o vídeo dublado!")
    
    # 1. Remove vídeo original
    try:
        if os.path.exists("video_original.txt"):
            with open("video_original.txt", "r", encoding="utf-8") as f:
                video_original_path = f.read().strip()
                
            if os.path.exists(video_original_path):
                safe_remove(video_original_path)
                logger.info(f"✅ Vídeo original removido: {video_original_path}")
    except Exception as e:
        logger.warning(f"⚠️ Erro ao remover vídeo original: {e}")
    
    # 2. Arquivos JSON e temporários na raiz
    files_to_remove = [
        "transcricao.json",
        "transcricao_pt.json",
        "frases_pt.json",
        "voz_dublada.wav",
        "audio_final_mix.wav",
        "video_original.txt"
    ]
    
    for f in files_to_remove:
        safe_remove(f)
        
    # 3. Diretórios de trabalho
    dirs_to_remove = [
        config.get("paths.tts_output_dir", "audios_frases_pt"),
        config.get("paths.stretched_dir", "audios_frases_pt_stretched"),
        "separated",  # ← IMPORTANTE: Remove stems do Demucs
        "temp",
    ]
    
    for d in dirs_to_remove:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
                logger.info(f"✅ Diretório removido: {d}")
            except Exception as e:
                logger.warning(f"⚠️ Erro ao remover diretório {d}: {e}")

    # Cache: remove tudo EXCETO o cache do Coqui TTS (cache/tts_home),
    # porque ele guarda os modelos e o aceite do CPML (tos_agreed.txt).
    cache_dir = config.get("paths.cache_dir", "cache")
    if os.path.isdir(cache_dir):
        try:
            for item in os.listdir(cache_dir):
                # Mantém o cache do TTS para evitar re-download + prompt de termos.
                if item.lower() == "tts_home":
                    continue
                full = os.path.join(cache_dir, item)
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                else:
                    safe_remove(full)
            logger.info(f"✅ Cache limpo (preservado: {os.path.join(cache_dir, 'tts_home')})")
        except Exception as e:
            logger.warning(f"⚠️ Erro ao limpar cache: {e}")

    # 4. Remove TODOS os arquivos WAV na raiz (chunks de voz)
    wav_count = 0
    for f in glob.glob("*.wav"):
        # Remove qualquer WAV que não seja parte de um nome de vídeo dublado
        if "_dublado" not in f:
            safe_remove(f)
            wav_count += 1
    
    if wav_count > 0:
        logger.info(f"✅ Removidos {wav_count} arquivos WAV temporários")
    
    # 5. Lista vídeos dublados encontrados
    videos_dublados = glob.glob("*_dublado.mp4")
    if videos_dublados:
        logger.info("=" * 60)
        logger.info("✅ LIMPEZA CONCLUÍDA COM SUCESSO!")
        logger.info("=" * 60)
        logger.info("📹 Vídeos dublados mantidos:")
        for video in videos_dublados:
            size_mb = os.path.getsize(video) / (1024 * 1024)
            logger.info(f"   • {video} ({size_mb:.1f} MB)")
        logger.info("=" * 60)
    else:
        logger.warning("⚠️ Nenhum vídeo dublado encontrado!")
        logger.warning("   Certifique-se que o processo de dublagem foi concluído.")

if __name__ == "__main__":
    limpar()