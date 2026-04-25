"""
🗄️ Cache Manager - Sistema de Cache Inteligente

Salva resultados de cada etapa do pipeline para reprocessamento instantâneo.

Funcionalidades:
- Hash de vídeos para identificação única
- Cache por etapa (transcrição, tradução, frases, etc)
- Invalidação seletiva
- Limpeza automática de cache antigo
"""

import os
import json
import hashlib
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from logger import setup_logger
from utils import load_json, save_json, ensure_dir

logger = setup_logger(__name__)


class CacheManager:
    """Gerenciador de cache para resultados do pipeline."""
    
    def __init__(self, cache_dir: str = "cache"):
        """
        Inicializa o gerenciador de cache.
        
        Args:
            cache_dir: Diretório raiz para armazenar cache
        """
        self.cache_dir = Path(cache_dir)
        ensure_dir(str(self.cache_dir))
        
        # Diretórios de cache por etapa
        self.steps = {
            "transcription": self.cache_dir / "transcription",
            "translation": self.cache_dir / "translation", 
            "phrases": self.cache_dir / "phrases",
            "dubbing": self.cache_dir / "dubbing",
            "metadata": self.cache_dir / "metadata"
        }
        
        # Cria todos os diretórios
        for step_dir in self.steps.values():
            ensure_dir(str(step_dir))
            
        logger.debug("CacheManager inicializado")
    
    def get_video_hash(self, video_path: str, config_params: Optional[Dict] = None) -> str:
        """
        Gera hash único para um vídeo + configurações.
        
        Args:
            video_path: Caminho do vídeo
            config_params: Parâmetros de configuração relevantes (opcional)
            
        Returns:
            Hash MD5 hexadecimal
        """
        hasher = hashlib.md5()
        
        # Hash do conteúdo do arquivo
        try:
            with open(video_path, 'rb') as f:
                # Lê primeiros 10MB + últimos 10MB (assinatura do arquivo)
                chunk_size = 10 * 1024 * 1024  # 10 MB
                
                # Início do arquivo
                chunk = f.read(chunk_size)
                hasher.update(chunk)
                
                # Fim do arquivo se for grande
                file_size = os.path.getsize(video_path)
                if file_size > chunk_size * 2:
                    f.seek(-chunk_size, 2)  # Vai para final - 10MB
                    chunk = f.read(chunk_size)
                    hasher.update(chunk)
                    
        except Exception as e:
            logger.warning(f"Erro ao gerar hash do vídeo, usando apenas nome: {e}")
            # Fallback: usa apenas nome e tamanho
            hasher.update(video_path.encode())
            hasher.update(str(os.path.getsize(video_path)).encode())
        
        # Adiciona parâmetros de config se fornecidos
        if config_params:
            params_str = json.dumps(config_params, sort_keys=True)
            hasher.update(params_str.encode())
        
        return hasher.hexdigest()
    
    def get_cache_path(self, step: str, video_hash: str, extension: str = "json") -> Path:
        """
        Retorna caminho do arquivo de cache para uma etapa.
        
        Args:
            step: Nome da etapa (transcription, translation, etc)
            video_hash: Hash do vídeo
            extension: Extensão do arquivo (padrão: json)
            
        Returns:
            Path do arquivo de cache
        """
        if step not in self.steps:
            raise ValueError(f"Etapa inválida: {step}. Opções: {list(self.steps.keys())}")
        
        return self.steps[step] / f"{video_hash}.{extension}"
    
    def has_cache(self, step: str, video_hash: str) -> bool:
        """
        Verifica se existe cache para uma etapa.
        
        Args:
            step: Nome da etapa
            video_hash: Hash do vídeo
            
        Returns:
            True se cache existe e é válido
        """
        cache_path = self.get_cache_path(step, video_hash)
        
        if not cache_path.exists():
            return False
        
        # Verifica metadados do cache
        try:
            metadata = self.get_metadata(video_hash)
            if metadata and step in metadata.get("cached_steps", {}):
                # Cache existe e está registrado
                return True
        except:
            pass
        
        # Cache existe mas não há metadados, assume válido
        return True
    
    def get_cache(self, step: str, video_hash: str) -> Optional[Any]:
        """
        Recupera dados do cache.
        
        Args:
            step: Nome da etapa
            video_hash: Hash do vídeo
            
        Returns:
            Dados do cache ou None se não existir
        """
        if not self.has_cache(step, video_hash):
            return None
        
        cache_path = self.get_cache_path(step, video_hash)
        
        try:
            logger.info(f"✅ Carregando {step} do cache")
            return load_json(str(cache_path))
        except Exception as e:
            logger.warning(f"Erro ao carregar cache de {step}: {e}")
            return None
    
    def set_cache(self, step: str, video_hash: str, data: Any) -> bool:
        """
        Salva dados no cache.
        
        Args:
            step: Nome da etapa
            video_hash: Hash do vídeo
            data: Dados a serem salvos
            
        Returns:
            True se salvou com sucesso
        """
        cache_path = self.get_cache_path(step, video_hash)
        
        try:
            save_json(data, str(cache_path))
            
            # Atualiza metadados
            self.update_metadata(video_hash, step)
            
            logger.info(f"💾 {step} salvo no cache")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar cache de {step}: {e}")
            return False
    
    def get_metadata(self, video_hash: str) -> Optional[Dict]:
        """
        Recupera metadados do cache de um vídeo.
        
        Args:
            video_hash: Hash do vídeo
            
        Returns:
            Dicionário de metadados ou None
        """
        metadata_path = self.get_cache_path("metadata", video_hash)
        
        if not metadata_path.exists():
            return None
        
        try:
            return load_json(str(metadata_path))
        except:
            return None
    
    def update_metadata(self, video_hash: str, step: str = None):
        """
        Atualiza metadados do cache.
        
        Args:
            video_hash: Hash do vídeo
            step: Etapa atualizada (opcional)
        """
        metadata_path = self.get_cache_path("metadata", video_hash)
        
        # Carrega metadados existentes ou cria novo
        if metadata_path.exists():
            try:
                metadata = load_json(str(metadata_path))
            except:
                metadata = {}
        else:
            metadata = {}
        
        # Atualiza timestamp
        metadata["last_updated"] = datetime.now().isoformat()
        
        # Registra etapa se fornecida
        if step:
            if "cached_steps" not in metadata:
                metadata["cached_steps"] = {}
            
            metadata["cached_steps"][step] = {
                "timestamp": datetime.now().isoformat(),
                "size_bytes": os.path.getsize(str(self.get_cache_path(step, video_hash)))
            }
        
        # Salva metadados
        try:
            save_json(metadata, str(metadata_path))
        except Exception as e:
            logger.warning(f"Erro ao salvar metadados: {e}")
    
    def clear_cache(self, video_hash: Optional[str] = None, step: Optional[str] = None):
        """
        Limpa cache.
        
        Args:
            video_hash: Hash específico (None = todos)
            step: Etapa específica (None = todas)
        """
        if video_hash and step:
            # Limpa cache específico
            cache_path = self.get_cache_path(step, video_hash)
            if cache_path.exists():
                os.remove(cache_path)
                logger.info(f"🗑️ Cache {step} removido para hash {video_hash[:8]}...")
        
        elif video_hash:
            # Limpa todos os caches de um vídeo
            for step_name in self.steps.keys():
                cache_path = self.get_cache_path(step_name, video_hash)
                if cache_path.exists():
                    os.remove(cache_path)
            logger.info(f"🗑️ Todo cache removido para hash {video_hash[:8]}...")
        
        elif step:
            # Limpa todos os caches de uma etapa
            step_dir = self.steps[step]
            for cache_file in step_dir.glob("*.json"):
                os.remove(cache_file)
            logger.info(f"🗑️ Todos os caches de {step} removidos")
        
        else:
            # Limpa tudo
            for step_dir in self.steps.values():
                for cache_file in step_dir.glob("*.json"):
                    os.remove(cache_file)
            logger.info("🗑️ Todo o cache foi limpo")
    
    def cleanup_old_cache(self, days: int = 30):
        """
        Remove caches mais antigos que N dias.
        
        Args:
            days: Número de dias para considerar cache antigo
        """
        cutoff = datetime.now() - timedelta(days=days)
        removed_count = 0
        
        for step_dir in self.steps.values():
            for cache_file in step_dir.glob("*.json"):
                # Verifica data de modificação
                mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
                if mtime < cutoff:
                    cache_file.unlink()
                    removed_count += 1
        
        if removed_count > 0:
            logger.info(f"🗑️ {removed_count} arquivos de cache antigos removidos")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Retorna estatísticas do cache.
        
        Returns:
            Dicionário com estatísticas
        """
        stats = {
            "total_videos": 0,
            "total_size_mb": 0,
            "steps": {}
        }
        
        # Conta vídeos únicos através dos metadados
        metadata_files = list(self.steps["metadata"].glob("*.json"))
        stats["total_videos"] = len(metadata_files)
        
        # Estatísticas por etapa
        for step_name, step_dir in self.steps.items():
            cache_files = list(step_dir.glob("*.json"))
            total_size = sum(f.stat().st_size for f in cache_files)
            
            stats["steps"][step_name] = {
                "count": len(cache_files),
                "size_mb": round(total_size / (1024 * 1024), 2)
            }
            
            stats["total_size_mb"] += stats["steps"][step_name]["size_mb"]
        
        stats["total_size_mb"] = round(stats["total_size_mb"], 2)
        
        return stats


# Singleton global
cache_manager = CacheManager()
