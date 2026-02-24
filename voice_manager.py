import os
import json
from pathlib import Path

from config_loader import config
from logger import setup_logger
from utils import load_json, save_json

logger = setup_logger(__name__)

class VoiceManager:
    """
    Gerencia múltiplas referências de voz para dublagem multi-falante
    """
    
    def __init__(self, voices_config_file="voice_references.json"):
        self.config_file = voices_config_file
        self.voices = self.load_voices()
    
    def load_voices(self):
        """Carrega referências de voz do arquivo de configuração"""
        if os.path.isfile(self.config_file):
            try:
                return load_json(self.config_file)
            except Exception as e:
                logger.warning(f"Erro ao carregar {self.config_file}: {e}")
        return {}
    
    def save_voices(self):
        """Salva referências de voz"""
        save_json(self.voices, self.config_file)
        logger.debug(f"Referências de voz salvas em {self.config_file}")
    
    def add_voice(self, speaker_id, audio_path, name=None):
        """
        Adiciona uma referência de voz
        
        Args:
            speaker_id: ID do falante (ex: "SPEAKER_00")
            audio_path: Caminho para arquivo de áudio de referência
            name: Nome amigável (opcional)
        """
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Arquivo não encontrado: {audio_path}")
        
        self.voices[speaker_id] = {
            "audio_path": os.path.abspath(audio_path),
            "name": name or speaker_id
        }
        self.save_voices()
        logger.info(f"✅ Voz adicionada: {speaker_id} -> {audio_path}")
    
    def remove_voice(self, speaker_id):
        """Remove uma referência de voz"""
        if speaker_id in self.voices:
            del self.voices[speaker_id]
            self.save_voices()
            logger.info(f"🗑 Voz removida: {speaker_id}")
    
    def get_voice(self, speaker_id):
        """Obtém a referência de voz para um falante"""
        return self.voices.get(speaker_id)
    
    def get_all_voices(self):
        """Retorna todas as referências de voz"""
        return self.voices.copy()
    
    def map_speakers_automatically(self, diarization_segments, vocals_dir):
        """
        Mapeia automaticamente falantes para referências de voz
        baseado em arquivos vocals_SPEAKER_XX.wav extraídos
        
        Args:
            diarization_segments: Lista de segmentos de diarização
            vocals_dir: Diretório com arquivos vocals separados por falante
        """
        unique_speakers = set(seg["speaker"] for seg in diarization_segments)
        
        for speaker in unique_speakers:
            # Procura por arquivo vocals específico do falante
            vocal_file = os.path.join(vocals_dir, f"vocals_{speaker}.wav")
            
            if os.path.isfile(vocal_file):
                self.add_voice(speaker, vocal_file, name=f"Voz {speaker[-2:]}")
            else:
                logger.warning(f"⚠️ Arquivo de voz não encontrado para {speaker}: {vocal_file}")
    
    def assign_default_voice(self, speaker_id, default_vocal_path):
        """
        Atribui uma voz padrão a um falante se ele não tiver uma
        
        Args:
            speaker_id: ID do falante
            default_vocal_path: Caminho para vocal padrão
        """
        if speaker_id not in self.voices:
            if os.path.isfile(default_vocal_path):
                self.add_voice(speaker_id, default_vocal_path, name=f"Voz Padrão ({speaker_id})")
            else:
                logger.warning(f"⚠️ Vocal padrão não encontrado: {default_vocal_path}")


# Instância global
voice_manager = VoiceManager()
