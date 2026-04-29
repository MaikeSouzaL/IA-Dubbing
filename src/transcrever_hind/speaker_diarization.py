import os
import sys
import json
import numpy as np
from pathlib import Path

from config_loader import config
from logger import setup_logger, log_progress
from utils import load_json, save_json

logger = setup_logger(__name__)

def perform_speaker_diarization(audio_path, num_speakers=None):
    """
    Realiza diarização de falantes usando pyannote.audio
    
    Args:
        audio_path: Caminho para o arquivo de áudio
        num_speakers: Número esperado de falantes (None para detecção automática)
    
    Returns:
        Lista de segmentos com informações de falante:
        [{"start": 0.0, "end": 2.5, "speaker": "SPEAKER_00"}, ...]
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        if config.get("app.offline_mode", False):
            logger.warning("pyannote.audio nao instalado e modo offline ativo. Diarizacao indisponivel.")
            return None
        logger.warning("pyannote.audio não instalado. Instalando...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "pyannote.audio"], check=False)
        from pyannote.audio import Pipeline
    
    logger.info("🎭 Iniciando diarização de falantes...")
    
    # Carrega o pipeline de diarização
    # Nota: Requer HuggingFace token para modelos privados
    try:
        hf_token = (
            config.get("models.pyannote.hf_token", None)
            or os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGINGFACE_TOKEN")
        )
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token
        )
    except Exception as e:
        logger.error(f"Erro ao carregar pipeline de diarização: {e}")
        logger.info("💡 Dica: Configure seu HuggingFace token em config.yaml: models.pyannote.hf_token")
        logger.info("💡 Ou visite: https://huggingface.co/pyannote/speaker-diarization")
        return None
    
    # Move para GPU se disponível
    import torch
    if torch.cuda.is_available():
        pipeline = pipeline.to(torch.device("cuda"))
        logger.info("✅ Usando GPU para diarização")
    
    # Executa a diarização
    params = {}
    if num_speakers:
        params["num_speakers"] = num_speakers
    
    diarization = pipeline(audio_path, **params)
    
    # Converte para lista de segmentos
    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker
        })
    
    # Estatísticas
    unique_speakers = set(seg["speaker"] for seg in segments)
    logger.info(f"✅ Diarização concluída: {len(unique_speakers)} falantes detectados")
    logger.info(f"   Falantes: {', '.join(sorted(unique_speakers))}")
    
    return segments


def assign_speakers_to_phrases(frases_pt_json, diarization_segments):
    """
    Atribui falantes às frases baseado na sobreposição temporal
    
    Args:
        frases_pt_json: Caminho para frases_pt.json
        diarization_segments: Lista de segmentos de diarização
    
    Returns:
        Frases atualizadas com informação de falante
    """
    if not diarization_segments:
        logger.warning("⚠️ Sem dados de diarização. Usando falante único.")
        return None
    
    frases = load_json(frases_pt_json)
    
    logger.info("🔗 Atribuindo falantes às frases...")
    
    for frase in frases:
        phrase_start = frase.get("start", 0.0)
        phrase_end = frase.get("end", phrase_start)
        phrase_mid = (phrase_start + phrase_end) / 2
        
        # Encontra o segmento de diarização que mais se sobrepõe
        best_overlap = 0
        best_speaker = "SPEAKER_00"  # Fallback
        
        for seg in diarization_segments:
            seg_start = seg["start"]
            seg_end = seg["end"]
            
            # Calcula sobreposição
            overlap_start = max(phrase_start, seg_start)
            overlap_end = min(phrase_end, seg_end)
            overlap = max(0, overlap_end - overlap_start)
            
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = seg["speaker"]
            
            # Se o ponto médio estiver no segmento, prioriza
            if seg_start <= phrase_mid <= seg_end:
                best_speaker = seg["speaker"]
                break
        
        frase["speaker"] = best_speaker
    
    # Salva frases atualizadas
    save_json(frases, frases_pt_json)
    
    # Estatísticas
    speaker_counts = {}
    for frase in frases:
        spk = frase.get("speaker", "UNKNOWN")
        speaker_counts[spk] = speaker_counts.get(spk, 0) + 1
    
    logger.info("✅ Atribuição de falantes concluída:")
    for spk, count in sorted(speaker_counts.items()):
        logger.info(f"   {spk}: {count} frases")
    
    return frases


if __name__ == "__main__":
    # Teste standalone
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python speaker_diarization.py <audio_path> [num_speakers]")
        sys.exit(1)
    
    audio = sys.argv[1]
    num_spk = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    if not os.path.isfile(audio):
        logger.error(f"Arquivo não encontrado: {audio}")
        sys.exit(1)
    
    # Executa diarização
    segments = perform_speaker_diarization(audio, num_spk)
    
    if segments:
        # Salva resultado
        output = "diarization_output.json"
        save_json(segments, output)
        logger.info(f"✅ Resultado salvo em: {output}")
        
        # Se frases_pt.json existir, atribui falantes
        if os.path.isfile("frases_pt.json"):
            assign_speakers_to_phrases("frases_pt.json", segments)
