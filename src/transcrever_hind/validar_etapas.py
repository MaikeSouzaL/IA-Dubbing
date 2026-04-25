"""
Script de validação completo do sistema de dublagem
Verifica se todas as etapas estão sendo executadas corretamente
"""
import os
import sys
import json
from pathlib import Path
from colorama import init, Fore, Back, Style
import subprocess

# Inicializa colorama
init(autoreset=True)

class ValidadorEtapas:
    def __init__(self):
        self.erros = []
        self.avisos = []
        self.sucessos = []
        
    def print_header(self, texto):
        print(f"\n{Fore.CYAN}{Style.BRIGHT}{'='*70}")
        print(f"{texto.center(70)}")
        print(f"{'='*70}{Style.RESET_ALL}\n")
        
    def print_step(self, numero, nome):
        print(f"\n{Fore.YELLOW}{Style.BRIGHT}[ETAPA {numero}] {nome}{Style.RESET_ALL}")
        print(f"{'-'*70}")
        
    def check_file(self, filepath, descricao):
        """Verifica se um arquivo existe"""
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {descricao}: {filepath} ({size:,} bytes)")
            self.sucessos.append(f"{descricao} OK")
            return True
        else:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} {descricao}: {filepath} {Fore.RED}NÃO ENCONTRADO{Style.RESET_ALL}")
            self.erros.append(f"{descricao} não encontrado: {filepath}")
            return False
            
    def check_dir(self, dirpath, descricao):
        """Verifica se um diretório existe e tem conteúdo"""
        if os.path.exists(dirpath) and os.path.isdir(dirpath):
            files = os.listdir(dirpath)
            count = len(files)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {descricao}: {dirpath} ({count} arquivos)")
            self.sucessos.append(f"{descricao} OK ({count} arquivos)")
            return True
        else:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} {descricao}: {dirpath} {Fore.RED}NÃO ENCONTRADO{Style.RESET_ALL}")
            self.erros.append(f"{descricao} não encontrado: {dirpath}")
            return False
            
    def check_json_content(self, filepath, descricao, campos_obrigatorios=None):
        """Verifica se um JSON existe e tem os campos necessários"""
        if not os.path.exists(filepath):
            print(f"  {Fore.RED}✗{Style.RESET_ALL} {descricao}: {filepath} {Fore.RED}NÃO ENCONTRADO{Style.RESET_ALL}")
            self.erros.append(f"{descricao} não encontrado: {filepath}")
            return False
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if not isinstance(data, list):
                print(f"  {Fore.RED}✗{Style.RESET_ALL} {descricao}: não é uma lista")
                self.erros.append(f"{descricao} deve ser uma lista")
                return False
                
            if len(data) == 0:
                print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} {descricao}: lista vazia")
                self.avisos.append(f"{descricao} está vazio")
                return False
                
            # Verifica campos obrigatórios no primeiro item
            if campos_obrigatorios:
                primeiro_item = data[0]
                campos_faltando = [c for c in campos_obrigatorios if c not in primeiro_item]
                
                if campos_faltando:
                    print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} {descricao}: campos faltando - {', '.join(campos_faltando)}")
                    self.avisos.append(f"{descricao} falta campos: {', '.join(campos_faltando)}")
                else:
                    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {descricao}: {len(data)} items com campos corretos")
                    self.sucessos.append(f"{descricao} OK ({len(data)} items)")
                    return True
            else:
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {descricao}: {len(data)} items")
                self.sucessos.append(f"{descricao} OK ({len(data)} items)")
                return True
                
        except json.JSONDecodeError as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} {descricao}: JSON inválido - {e}")
            self.erros.append(f"{descricao} tem JSON inválido")
            return False
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} {descricao}: erro ao ler - {e}")
            self.erros.append(f"{descricao} erro de leitura")
            return False
            
    def check_python_script(self, filepath, descricao):
        """Verifica se um script Python existe e tem sintaxe válida"""
        if not os.path.exists(filepath):
            print(f"  {Fore.RED}✗{Style.RESET_ALL} {descricao}: {filepath} {Fore.RED}NÃO ENCONTRADO{Style.RESET_ALL}")
            self.erros.append(f"{descricao} não encontrado: {filepath}")
            return False
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                code = f.read()
            compile(code, filepath, 'exec')
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {descricao}: sintaxe válida")
            self.sucessos.append(f"{descricao} OK")
            return True
        except SyntaxError as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} {descricao}: erro de sintaxe - linha {e.lineno}")
            self.erros.append(f"{descricao} tem erro de sintaxe")
            return False
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} {descricao}: aviso - {e}")
            self.avisos.append(f"{descricao} aviso")
            return True
            
    def check_config(self):
        """Verifica a configuração do sistema"""
        self.print_step(0, "VERIFICANDO CONFIGURAÇÃO DO SISTEMA")
        
        # Verifica config.yaml
        if self.check_file("config.yaml", "Arquivo de configuração"):
            from config_loader import config
            
            # Verifica configurações críticas
            target_lang = config.get("translation.target_language", None)
            if target_lang:
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Idioma alvo configurado: {target_lang}")
            else:
                print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Idioma alvo não configurado")
                
            whisper_model = config.get("models.whisper.size", None)
            if whisper_model:
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Modelo Whisper: {whisper_model}")
            else:
                print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Modelo Whisper não configurado")
                
        # Verifica scripts principais
        scripts = [
            ("transcrever.py", "Script de transcrição"),
            ("traduzir_para_pt.py", "Script de tradução"),
            ("extrair_frases_pt.py", "Script de extração de frases"),
            ("dublar_frases_pt.py", "Script de dublagem"),
            ("sincronizar_e_juntar.py", "Script de sincronização"),
            ("limpar_projeto.py", "Script de limpeza"),
        ]
        
        for script, desc in scripts:
            self.check_python_script(script, desc)
            
    def valida_etapa1_transcrever(self):
        """Valida ETAPA 1: Transcrever"""
        self.print_step(1, "TRANSCREVER")
        
        # Verifica se há vídeo original
        has_video = False
        if os.path.exists("video_original.txt"):
            with open("video_original.txt", "r", encoding="utf-8") as f:
                video_path = f.read().strip()
                if os.path.exists(video_path):
                    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Vídeo original: {video_path}")
                    has_video = True
                else:
                    print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Vídeo original não encontrado: {video_path}")
        else:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} video_original.txt não encontrado")
            
        # Verifica saída do Demucs (separação de áudio)
        separated_dirs = list(Path("separated").rglob("htdemucs")) if os.path.exists("separated") else []
        
        if separated_dirs:
            for sep_dir in separated_dirs[:1]:  # Mostra só o primeiro
                # Modelo 4-stems
                stems_4 = ["vocals.wav", "bass.wav", "drums.wav", "other.wav"]
                has_4_stems = all(os.path.exists(sep_dir / stem) for stem in stems_4)
                
                # Modelo 2-stems
                has_2_stems = os.path.exists(sep_dir / "no_vocals.wav")
                
                if has_4_stems:
                    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Separação de áudio (4-stems): {sep_dir}")
                    for stem in stems_4:
                        size = os.path.getsize(sep_dir / stem)
                        print(f"    - {stem}: {size:,} bytes")
                elif has_2_stems:
                    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Separação de áudio (2-stems): {sep_dir}")
                    print(f"    - no_vocals.wav: {os.path.getsize(sep_dir / 'no_vocals.wav'):,} bytes")
                else:
                    print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Separação incompleta em: {sep_dir}")
        else:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Pasta 'separated' não encontrada ou vazia")
            
        # Verifica transcrição
        campos_transcricao = ["transcript", "start", "end", "words"]
        self.check_json_content("transcricao.json", "Transcrição original", campos_transcricao)
        
    def valida_etapa2_traduzir(self):
        """Valida ETAPA 2: Traduzir"""
        self.print_step(2, "TRADUZIR")
        
        campos_traducao = ["transcript", "transcript_pt", "start", "end"]
        self.check_json_content("transcricao_pt.json", "Transcrição traduzida", campos_traducao)
        
    def valida_etapa3_extrair_frases(self):
        """Valida ETAPA 3: Extrair Frases"""
        self.print_step(3, "EXTRAIR FRASES")
        
        campos_frases = ["frase_pt", "start", "end", "slot_dur"]
        self.check_json_content("frases_pt.json", "Frases extraídas", campos_frases)
        
    def valida_etapa4_dublar(self):
        """Valida ETAPA 4: Dublar"""
        self.print_step(4, "DUBLAR")
        
        # Verifica diretório de áudios dublados
        self.check_dir("audios_frases_pt", "Diretório de áudios TTS")
        
        # Conta quantos arquivos de áudio foram gerados
        if os.path.exists("audios_frases_pt"):
            audio_files = list(Path("audios_frases_pt").glob("*.wav"))
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Arquivos de áudio gerados: {len(audio_files)}")
            
            # Verifica se o número corresponde ao frases_pt.json
            if os.path.exists("frases_pt.json"):
                with open("frases_pt.json", 'r', encoding='utf-8') as f:
                    frases = json.load(f)
                    if len(audio_files) == len(frases):
                        print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Número de áudios corresponde ao número de frases")
                    elif len(audio_files) < len(frases):
                        print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Faltam {len(frases) - len(audio_files)} áudios")
                        self.avisos.append(f"Faltam áudios: {len(frases) - len(audio_files)}")
                    else:
                        print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Há {len(audio_files) - len(frases)} áudios extras")
        
    def valida_etapa5_sincronizar(self):
        """Valida ETAPA 5: Sincronizar e Juntar"""
        self.print_step(5, "SINCRONIZAR E JUNTAR")
        
        # Verifica diretório de áudios esticados
        self.check_dir("audios_frases_pt_stretched", "Diretório de áudios sincronizados")
        
        # Verifica voz dublada
        self.check_file("voz_dublada.wav", "Voz dublada completa")
        
        # Verifica mixagem final
        self.check_file("audio_final_mix.wav", "Mixagem final de áudio")
        
        # Verifica vídeo final
        video_files = list(Path(".").glob("*_dublado.mp4"))
        if video_files:
            for video in video_files:
                self.check_file(str(video), f"Vídeo final dublado")
        else:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Nenhum vídeo dublado (*_dublado.mp4) encontrado")
            self.avisos.append("Vídeo dublado não encontrado")
            
    def valida_etapa6_limpar(self):
        """Valida ETAPA 6: Limpeza (opcional)"""
        self.print_step(6, "LIMPEZA (OPCIONAL)")
        
        # Esta etapa remove arquivos temporários, então verificamos se foi executada
        # pela AUSÊNCIA de certos arquivos
        
        temp_files = [
            "voz_dublada.wav",
            "audio_final_mix.wav",
            "transcricao.json",
            "transcricao_pt.json",
            "frases_pt.json"
        ]
        
        cleaned = []
        not_cleaned = []
        
        for temp_file in temp_files:
            if not os.path.exists(temp_file):
                cleaned.append(temp_file)
            else:
                not_cleaned.append(temp_file)
                
        if cleaned:
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Arquivos removidos pela limpeza: {len(cleaned)}")
            for f in cleaned:
                print(f"    - {f}")
        
        if not_cleaned:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Arquivos temporários ainda presentes: {len(not_cleaned)}")
            print(f"    (Normal se a limpeza não foi executada)")
            for f in not_cleaned[:5]:  # Mostra só os primeiros 5
                print(f"    - {f}")
                
    def gerar_relatorio(self):
        """Gera relatório final"""
        self.print_header("RELATÓRIO FINAL DE VALIDAÇÃO")
        
        print(f"{Fore.GREEN}{'SUCESSOS:':<20} {len(self.sucessos)}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{'AVISOS:':<20} {len(self.avisos)}{Style.RESET_ALL}")
        print(f"{Fore.RED}{'ERROS:':<20} {len(self.erros)}{Style.RESET_ALL}")
        
        if self.erros:
            print(f"\n{Fore.RED}{Style.BRIGHT}ERROS ENCONTRADOS:{Style.RESET_ALL}")
            for erro in self.erros:
                print(f"  {Fore.RED}✗{Style.RESET_ALL} {erro}")
                
        if self.avisos:
            print(f"\n{Fore.YELLOW}{Style.BRIGHT}AVISOS:{Style.RESET_ALL}")
            for aviso in self.avisos:
                print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} {aviso}")
                
        # Status geral
        print(f"\n{'-'*70}")
        if len(self.erros) == 0:
            if len(self.avisos) == 0:
                print(f"{Fore.GREEN}{Style.BRIGHT}✅ SISTEMA VALIDADO COM SUCESSO!{Style.RESET_ALL}")
                print(f"{Fore.GREEN}Todas as etapas estão funcionando corretamente.{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}{Style.BRIGHT}⚠ SISTEMA VALIDADO COM AVISOS{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}O sistema está funcional mas há algumas observações.{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}{Style.BRIGHT}❌ SISTEMA COM PROBLEMAS{Style.RESET_ALL}")
            print(f"{Fore.RED}Corrija os erros antes de continuar.{Style.RESET_ALL}")
        print(f"{'-'*70}\n")
        
    def executar_validacao_completa(self):
        """Executa validação completa do sistema"""
        self.print_header("VALIDAÇÃO COMPLETA DO SISTEMA DE DUBLAGEM")
        
        self.check_config()
        self.valida_etapa1_transcrever()
        self.valida_etapa2_traduzir()
        self.valida_etapa3_extrair_frases()
        self.valida_etapa4_dublar()
        self.valida_etapa5_sincronizar()
        self.valida_etapa6_limpar()
        
        self.gerar_relatorio()
        

def main():
    """Função principal"""
    try:
        # Tenta instalar colorama se não estiver disponível
        try:
            import colorama
        except ImportError:
            print("Instalando colorama...")
            subprocess.run([sys.executable, "-m", "pip", "install", "colorama"], check=True)
            import colorama
            
        validador = ValidadorEtapas()
        validador.executar_validacao_completa()
        
        # Retorna código de saída apropriado
        if len(validador.erros) > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}Validação interrompida pelo usuário.{Style.RESET_ALL}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Fore.RED}{Style.BRIGHT}ERRO CRÍTICO:{Style.RESET_ALL} {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
