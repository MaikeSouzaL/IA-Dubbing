import os
import pickle
import shutil
import sys
import torch
from pathlib import Path
from typing import Any, Optional
import whisper

# Adiciona caminho do TTS se necessário
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "TTS"))
try:
    from TTS.api import TTS
except ImportError:
    TTS = None

from logger import setup_logger
from config_loader import config
from utils import ensure_dir

logger = setup_logger("model_cache")

class ModelCache:
    """
    Gerencia o cache de modelos de IA (Whisper, TTS) para evitar recarregamento
    desnecessário e acelerar a inicialização.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelCache, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.cache_dir = Path(config.get("paths.cache_dir", "cache"))
        ensure_dir(self.cache_dir)
        self._memory_cache = {}
        self._initialized = True
        
        # Detecta dispositivo disponível
        self.device = self._detect_device()
        logger.info(f"🖥️ Dispositivo detectado: {self.device}")
        
        if self.device == "cuda":
            gpu_name = torch.cuda.get_device_name(0)
            vram_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logger.info(f"🎮 GPU: {gpu_name} ({vram_total:.1f} GB VRAM)")
    
    def _detect_device(self):
        """Detecta o melhor dispositivo disponível"""
        device_config = config.get("models.whisper.device", "auto")
        
        if device_config != "auto":
            return device_config
        
        if torch.cuda.is_available():
            return "cuda"
        else:
            logger.warning("⚠️ CUDA não disponível. Usando CPU (será mais lento)")
            return "cpu"
        
    def get_whisper(self, model_size: str = "medium", use_fp16: bool = None) -> Any:
        """
        Carrega ou retorna modelo Whisper do cache.
        AGORA COM SUPORTE A GPU E FP16! 🚀
        
        Args:
            model_size: Tamanho do modelo (tiny, base, small, medium, large)
            use_fp16: Se True, usa FP16 (half precision) na GPU para economizar VRAM
                     Se None, usa configuração de config.yaml
        
        NOTA: FP16 no Whisper funciona via torch.autocast, não .half() direto
        """
        # Verifica configuração FP16
        if use_fp16 is None:
            use_fp16 = config.get("models.whisper.use_fp16", False)  # Desabilitado por padrão
        
        # Chave de cache NÃO inclui FP16 (modelo é sempre FP32, FP16 vem via autocast)
        cache_key = f"whisper_{model_size}_{self.device}"
        
        # 1. Tenta memória RAM
        if cache_key in self._memory_cache:
            logger.debug(f"Modelo Whisper ({model_size}) carregado do cache.")
            return self._memory_cache[cache_key]
            
        # 2. Carrega novo COM GPU
        logger.info(f"Carregando modelo Whisper ({model_size}) no {self.device.upper()}...")
        
        # Whisper sempre carrega em FP32, FP16 será usado via autocast durante inferência
        if use_fp16 and self.device == "cuda":
            logger.info(f"⚡ FP16 será usado via autocast durante transcrição")
            logger.info(f"   💾 Economia de VRAM: ~20-30% (via mixed precision)")
            logger.info(f"   ⚡ Velocidade: +15-20% esperado")
        
        try:
            # Carrega no dispositivo correto (sempre em FP32)
            model = whisper.load_model(model_size, device=self.device)
            
            if self.device == "cuda":
                logger.info(f"✅ Whisper carregado na GPU (FP32 + autocast FP16)")
            else:
                logger.info(f"✅ Whisper carregado na CPU")
            
            # Salva flag de FP16 no modelo para uso posterior
            model._use_fp16 = use_fp16 and self.device == "cuda"
            
            self._memory_cache[cache_key] = model
            return model
            
        except Exception as e:
            logger.error(f"Erro ao carregar Whisper: {e}")
            # Fallback para CPU se GPU falhar
            if self.device == "cuda":
                logger.warning("⚠️ Tentando carregar Whisper na CPU como fallback...")
                model = whisper.load_model(model_size, device="cpu")
                model._use_fp16 = False
                self._memory_cache[f"whisper_{model_size}_cpu"] = model
                return model
            raise

    def get_tts(self, model_name: str, device: str = "auto") -> Any:
        """
        Carrega ou retorna modelo TTS.
        Nota: TTS models são complexos de serializar com pickle, 
        então focamos em cache em memória para a sessão atual.
        """
        if TTS is None:
            raise RuntimeError("Biblioteca TTS não instalada.")

        # Garante cache do Coqui TTS em pasta local do projeto (evita AppData quebrado/corrompido)
        self._configure_tts_home()
        # Se o diretório do modelo existir mas estiver incompleto, força re-download.
        self._ensure_coqui_model_present(model_name)
            
        cache_key = f"tts_{model_name}_{device}"
        
        if cache_key in self._memory_cache:
            logger.debug(f"Modelo TTS ({model_name}) carregado da memória.")
            return self._memory_cache[cache_key]
            
        logger.info(f"Carregando modelo TTS ({model_name})...")
        
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
            
        try:
            tts = TTS(model_name=model_name, progress_bar=False)
            tts.to(device)
            
            if device == "cuda":
                logger.info(f"✅ TTS carregado na GPU")
            else:
                logger.info(f"✅ TTS carregado na CPU")
            
            self._memory_cache[cache_key] = tts
            return tts
        except Exception as e:
            logger.error(f"Erro ao carregar TTS: {e}")
            raise

    def _configure_tts_home(self) -> Path:
        """Define `TTS_HOME` para um diretório local (se ainda não definido).

        Isso torna o projeto mais portátil e evita caches corrompidos em
        `AppData/Local/tts` (causa comum do erro `model.pth` faltando).
        """
        if os.environ.get("TTS_HOME"):
            return Path(os.environ["TTS_HOME"]).expanduser().resolve(strict=False)

        # Permite sobrescrever via config, caso o usuário queira.
        cfg_home = config.get("paths.tts_home", None)
        if cfg_home:
            home_path = Path(cfg_home)
            if not home_path.is_absolute():
                home_path = (Path(__file__).parent / home_path).resolve(strict=False)
        else:
            home_path = (Path(__file__).parent / self.cache_dir / "tts_home").resolve(strict=False)

        ensure_dir(home_path)
        os.environ["TTS_HOME"] = str(home_path)
        logger.debug(f"📦 TTS_HOME configurado: {home_path}")
        return home_path

    def _coqui_model_dir(self, model_name: str) -> Path:
        # `get_user_data_dir('tts')` aponta para `<TTS_HOME>/tts`.
        from TTS.utils.generic_utils import get_user_data_dir

        model_full_name = model_name.replace("/", "--")
        return Path(get_user_data_dir("tts")).joinpath(model_full_name)

    def _coqui_tos_agreed(self, model_dir: Path) -> bool:
        if os.environ.get("COQUI_TOS_AGREED") == "1":
            return True
        try:
            return model_dir.joinpath("tos_agreed.txt").exists()
        except Exception:
            return False

    def _ensure_coqui_model_present(self, model_name: str) -> None:
        """Valida a presença dos arquivos essenciais do modelo no cache local.

        Para XTTS, é comum a pasta existir e faltar `model.pth`, o que faz o
        Coqui dizer "already downloaded" mas falhar no load.
        """
        try:
            model_dir = self._coqui_model_dir(model_name)
        except Exception:
            # Se falhar por qualquer motivo, deixa o Coqui lidar.
            return

        if not model_dir.exists():
            return

        # Arquivo de checkpoint pode ter nomes diferentes dependendo do modelo.
        model_files = [
            model_dir / "model.pth",
            model_dir / "model_file.pth",
            model_dir / "model_file.pth.tar",
        ]
        has_model_file = any(p.exists() for p in model_files)
        has_config = (model_dir / "config.json").exists()

        if has_model_file and has_config:
            return

        # Pasta existe mas está incompleta -> limpa e força download.
        logger.warning(f"⚠️ Cache do Coqui TTS incompleto para {model_name}: {model_dir}")
        logger.warning("   Limpando pasta do modelo e forçando re-download...")

        # Se for XTTS e não houver TOS aceito, não tente baixar em modo não-interativo.
        if "xtts" in model_name.lower() and (not self._coqui_tos_agreed(model_dir)):
            allow_prompt = os.environ.get("COQUI_TOS_ALLOW_PROMPT") == "1"
            if (not sys.stdin.isatty()) and (not allow_prompt):
                raise RuntimeError(
                    "XTTS requer aceitar os termos (CPML). Rode `python dublar_frases_pt.py` no terminal uma vez "
                    "e aceite o prompt, ou defina a env `COQUI_TOS_AGREED=1`. "
                    "(Dica: para aceitar pela GUI, execute com `COQUI_TOS_ALLOW_PROMPT=1`.)"
                )

        try:
            shutil.rmtree(model_dir, ignore_errors=True)
        except Exception:
            pass

        try:
            from TTS.utils.manage import ModelManager

            mm = ModelManager(progress_bar=True, verbose=True)
            mm.download_model(model_name)
        except Exception as e:
            logger.error(f"Falha ao rebaixar modelo {model_name}: {e}")
            raise

    def clear_memory(self):
        """Limpa cache da memória RAM e VRAM."""
        self._memory_cache.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("Cache de modelos limpo.")

# Instância global
model_cache = ModelCache()
