import yaml
import os
from pathlib import Path
from typing import Any, Dict

class Config:
    """
    Carrega e gerencia as configurações do sistema a partir do arquivo config.yaml.
    Implementa o padrão Singleton para ser carregado apenas uma vez.
    """
    _instance = None
    _config: Dict[str, Any] = {}

    def __new__(cls, config_path: str = "config.yaml"):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load(config_path)
        return cls._instance

    def _load(self, config_path: str):
        """Carrega o arquivo YAML."""
        path = Path(config_path)
        if not path.exists():
            # Se não achar no diretório atual, tenta procurar na raiz do projeto
            # Assumindo que este script pode estar em src/ ou similar
            parent_path = Path(__file__).parent / config_path
            if parent_path.exists():
                path = parent_path
            else:
                print(f"⚠️ Aviso: Arquivo {config_path} não encontrado. Usando configurações padrão vazias.")
                return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
        except Exception as e:
            print(f"❌ Erro ao ler arquivo de configuração: {e}")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Obtém um valor da configuração usando notação de ponto.
        Ex: config.get('models.whisper.size', 'medium')
        """
        keys = key_path.split('.')
        value = self._config
        
        try:
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return default
            return value if value is not None else default
        except Exception:
            return default
    
    def save(self, config_path: str = "config.yaml"):
        """
        Salva as configurações atuais de volta no arquivo YAML.
        """
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            return True
        except Exception as e:
            print(f"❌ Erro ao salvar configuração: {e}")
            return False

# Instância global para ser importada
config = Config()
