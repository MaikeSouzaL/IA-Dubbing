import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from functools import wraps

from logger import setup_logger

logger = setup_logger("utils")

def load_json(path: str) -> Dict[str, Any]:
    """Carrega um arquivo JSON com tratamento de erros básico."""
    if not os.path.isfile(path):
        logger.error(f"Arquivo JSON não encontrado: {path}")
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON {path}: {e}")
        raise ValueError(f"JSON inválido: {e}")

def save_json(data: Any, path: str, indent: int = 2):
    """Salva dados em um arquivo JSON, criando diretórios se necessário."""
    try:
        # Garante que o diretório pai existe
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        logger.debug(f"JSON salvo em: {path}")
    except Exception as e:
        logger.error(f"Erro ao salvar JSON em {path}: {e}")
        raise

def ensure_dir(path: str):
    """Garante que um diretório existe."""
    Path(path).mkdir(parents=True, exist_ok=True)

def format_duration(seconds: float) -> str:
    """Formata segundos em HH:MM:SS."""
    if seconds is None:
        return "00:00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Decorator para tentar executar uma função várias vezes em caso de erro.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    logger.warning(f"Tentativa {attempt + 1}/{max_attempts} falhou para {func.__name__}: {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(current_delay)
                        current_delay *= backoff
            
            logger.error(f"Todas as {max_attempts} tentativas falharam para {func.__name__}.")
            raise last_exception
        return wrapper
    return decorator

def safe_remove(path: str):
    """Remove um arquivo sem gerar erro se ele não existir."""
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug(f"Arquivo removido: {path}")
    except Exception as e:
        logger.warning(f"Não foi possível remover {path}: {e}")
