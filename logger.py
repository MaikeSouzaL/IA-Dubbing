import logging
import sys
import os
from pathlib import Path
from datetime import datetime

def setup_logger(name: str, log_dir: str = "logs") -> logging.Logger:
    """
    Configura um logger que escreve tanto no console quanto em arquivo.
    
    Args:
        name: Nome do logger (geralmente __name__)
        log_dir: Diretório onde os arquivos de log serão salvos
    
    Returns:
        Um objeto logging.Logger configurado
    """
    # Garante que o diretório de logs existe
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Se já tiver handlers, não adiciona novamente para evitar duplicidade
    if logger.handlers:
        return logger
    
    # Formato do log
    # Ex: 2023-10-27 10:00:00 | transcrever | INFO | Mensagem
    formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 1. Handler para Console (apenas INFO e acima para não poluir)
    # Correção para Windows: Força stdout a usar UTF-8 para suportar emojis
    if sys.platform == "win32" and hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 2. Handler para Arquivo (DEBUG e acima, para auditoria completa)
    # Cria um arquivo novo por dia ou execução
    timestamp = datetime.now().strftime('%Y%m%d')
    log_file = os.path.join(log_dir, f"dubbing_system_{timestamp}.log")
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

def log_progress(logger, percent: float):
    """
    Registra uma mensagem especial de progresso para a GUI.
    Formato: PROGRESS: 50.5
    """
    # Garante que percent esteja entre 0 e 100
    percent = max(0.0, min(100.0, percent))
    logger.info(f"PROGRESS: {percent:.1f}")
