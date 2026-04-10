import sys
import os
import threading
import subprocess
import queue
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from pathlib import Path

# Tenta importar PIL para ícone (opcional)
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from config_loader import config
from logger import setup_logger

logger = setup_logger("gui")

# Setup CustomTkinter appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class DubbingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sistema de Dublagem Automática - AI Dubbing")
        self.root.geometry("950x800")
        self.root.minsize(900, 750)
        
        # Variáveis de controle
        self.video_path = ctk.StringVar()
        self.youtube_url = ctk.StringVar()
        self.input_mode = ctk.StringVar(value="file") # file ou url
        self.status_var = ctk.StringVar(value="Pronto")
        self.progress_var = ctk.DoubleVar(value=0.0)
        self.stage_var = ctk.StringVar(value="Aguardando início...")
        self.is_running = False
        self.process = None
        
        # Novas variáveis para funcionalidades
        self.keep_cut_videos = ctk.BooleanVar(value=config.get("app.keep_cut_videos", False))
        self.selected_videos_to_merge = []  # Lista de vídeos selecionados para merge
        
        # Fila para comunicação thread-safe com a GUI
        self.log_queue = queue.Queue()
        
        self.setup_ui()
        
        # Inicia loop de verificação de logs
        self.root.after(100, self.process_log_queue)

    def setup_ui(self):
        # Container Principal
        self.main_frame = ctk.CTkScrollableFrame(self.root, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Cabeçalho
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 20))
        ctk.CTkLabel(header_frame, text="🎬 Sistema de Dublagem Automática", 
                     font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"), 
                     text_color="#3b8ed0").pack(side="left")
        
        # Área de Entrada
        input_frame = ctk.CTkFrame(self.main_frame)
        input_frame.pack(fill="x", pady=(0, 20), ipady=10)
        
        ctk.CTkLabel(input_frame, text="Entrada de Vídeo", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        # Radio buttons para escolher modo
        mode_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        mode_frame.pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkRadioButton(mode_frame, text="Arquivo Local", variable=self.input_mode, value="file", command=self.toggle_input_mode).pack(side="left", padx=(0, 20))
        ctk.CTkRadioButton(mode_frame, text="YouTube URL", variable=self.input_mode, value="url", command=self.toggle_input_mode).pack(side="left")
        
        # Input de Arquivo
        self.file_input_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        self.file_input_frame.pack(fill="x", padx=15, pady=5)
        self.entry_file = ctk.CTkEntry(self.file_input_frame, textvariable=self.video_path, font=ctk.CTkFont(family="Consolas", size=12), placeholder_text="Caminho do vídeo...")
        self.entry_file.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(self.file_input_frame, text="📂 Procurar", font=ctk.CTkFont(size=13, weight="bold"), command=self.browse_file, width=120).pack(side="left")
        
        # Input de URL (inicialmente oculto)
        self.url_input_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        self.entry_url = ctk.CTkEntry(self.url_input_frame, textvariable=self.youtube_url, font=ctk.CTkFont(family="Consolas", size=12), placeholder_text="Cole a URL do YouTube aqui...")
        self.entry_url.pack(side="left", fill="x", expand=True)

        self.toggle_input_mode()
        
        # Configurações Rápidas
        config_frame = ctk.CTkFrame(self.main_frame)
        config_frame.pack(fill="x", pady=(0, 20), ipady=10)
        
        ctk.CTkLabel(config_frame, text="Configurações Rápidas", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        grid_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        grid_frame.pack(fill="x", padx=15, pady=5)
        
        # Linha 1
        ctk.CTkLabel(grid_frame, text="Modelo Whisper:").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=10)
        self.whisper_model = ctk.StringVar(value=config.get("models.whisper.size", "medium"))
        models = ["tiny", "base", "small", "medium", "large"]
        ctk.CTkComboBox(grid_frame, variable=self.whisper_model, values=models, width=140).grid(row=0, column=1, sticky="w", padx=0, pady=10)
        
        ctk.CTkLabel(grid_frame, text="Idioma Destino:").grid(row=0, column=2, sticky="w", padx=(30, 10), pady=10)
        self.target_lang = ctk.StringVar(value=config.get("translation.target_language", "pt"))
        
        langs = [
            ("pt", "🇵🇹 Português"), ("en", "🇬🇧 Inglês"), ("es", "🇪🇸 Espanhol"),
            ("fr", "🇫🇷 Francês"), ("de", "🇩🇪 Alemão"), ("it", "🇮🇹 Italiano"),
            ("pl", "🇵🇱 Polonês"), ("tr", "🇹🇷 Turco"), ("ru", "🇷🇺 Russo"),
            ("nl", "🇳🇱 Holandês"), ("cs", "🇨🇿 Tcheco"), ("ar", "🇸🇦 Árabe"),
            ("zh-cn", "🇨🇳 Chinês"), ("ja", "🇯🇵 Japonês"), ("hu", "🇭🇺 Húngaro"),
            ("ko", "🇰🇷 Coreano")
        ]
        lang_codes = [lang[0] for lang in langs]
        
        ctk.CTkComboBox(grid_frame, variable=self.target_lang, values=lang_codes, width=100).grid(row=0, column=3, sticky="w", padx=0, pady=10)
        
        self.clean_after = ctk.BooleanVar(value=config.get("app.clean_after_completion", True))
        ctk.CTkCheckBox(grid_frame, text="Limpar temporários", variable=self.clean_after).grid(row=0, column=4, sticky="w", padx=(30, 0), pady=10)
        
        # Linha 2 - Legendas
        ctk.CTkLabel(grid_frame, text="Legendas (.srt):").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=10)
        
        subtitle_frame = ctk.CTkFrame(grid_frame, fg_color="transparent")
        subtitle_frame.grid(row=1, column=1, columnspan=3, sticky="w")
        
        self.generate_subtitles = ctk.BooleanVar(value=config.get("app.generate_subtitles", True))
        ctk.CTkCheckBox(subtitle_frame, text="Gerar", variable=self.generate_subtitles).pack(side="left", padx=(0, 15))
        
        self.subtitle_original = ctk.BooleanVar(value=config.get("app.subtitle_original", True))
        ctk.CTkCheckBox(subtitle_frame, text="Original", variable=self.subtitle_original).pack(side="left", padx=15)
        
        self.subtitle_translated = ctk.BooleanVar(value=config.get("app.subtitle_translated", True))
        ctk.CTkCheckBox(subtitle_frame, text="Traduzida", variable=self.subtitle_translated).pack(side="left", padx=(15, 0))
        
        # Linha 3 - Vídeos Longos
        ctk.CTkLabel(grid_frame, text="Vídeos Longos:").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=10)
        ctk.CTkCheckBox(grid_frame, text="Manter vídeos cortados salvos", variable=self.keep_cut_videos).grid(row=2, column=1, columnspan=3, sticky="w", pady=10)
        
        # Linha 4 - Avançado (Múltiplas Vozes)
        ctk.CTkLabel(grid_frame, text="Avançado:").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=10)
        
        adv_frame = ctk.CTkFrame(grid_frame, fg_color="transparent")
        adv_frame.grid(row=3, column=1, columnspan=4, sticky="w")
        
        self.use_multi_voice = ctk.BooleanVar(value=config.get("app.use_multi_voice", False))
        self.chk_multi_voice = ctk.CTkCheckBox(adv_frame, text="Modo Entrevista (Múltiplas Vozes)", variable=self.use_multi_voice, command=self.toggle_multi_voice)
        self.chk_multi_voice.pack(side="left", padx=(0, 15))
        
        ctk.CTkLabel(adv_frame, text="Qtd Locutores:").pack(side="left", padx=(5, 5))
        self.expected_speakers = ctk.StringVar(value=str(config.get("app.expected_speakers", 2)))
        self.entry_speakers = ctk.CTkEntry(adv_frame, textvariable=self.expected_speakers, width=40)
        self.entry_speakers.pack(side="left")
        
        self.toggle_multi_voice()
        
        # Juntar Vídeos
        merge_frame = ctk.CTkFrame(self.main_frame)
        merge_frame.pack(fill="x", pady=(0, 20), ipady=10)
        
        ctk.CTkLabel(merge_frame, text="🔗 Juntar Vídeos Dublados", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        merge_inner = ctk.CTkFrame(merge_frame, fg_color="transparent")
        merge_inner.pack(fill="x", padx=15, pady=5)
        
        ctk.CTkLabel(merge_inner, text="Selecione os vídeos na ordem desejada:").pack(side="left", padx=(0, 15))
        ctk.CTkButton(merge_inner, text="📁 Selecionar", command=self.select_videos_to_merge, width=120).pack(side="left", padx=5)
        ctk.CTkButton(merge_inner, text="🔗 Juntar", command=self.merge_selected_videos, fg_color="#28a745", hover_color="#218838", width=100).pack(side="left", padx=5)
        
        self.merge_status_label = ctk.CTkLabel(merge_inner, text="Nenhum vídeo selecionado.", text_color="gray")
        self.merge_status_label.pack(side="left", padx=(15, 0))

        # Progresso e Logs
        log_frame = ctk.CTkFrame(self.main_frame)
        log_frame.pack(fill="both", expand=True, pady=(0, 20), ipady=10)
        
        ctk.CTkLabel(log_frame, text="Progresso e Logs", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        # Console de logs (permite input no final para responder prompts em CLI)
        self.log_textbox = ctk.CTkTextbox(log_frame, state="normal", font=ctk.CTkFont(family="Consolas", size=12), height=200)
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=5)

        # Estado do console interativo
        self._console_prompt = "> "
        self._console_prompt_start = None
        self._console_input_start = None
        self._running_process = None
        self._console_init_bindings()
        self._console_reset()
        
        # Footer Frame
        footer_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        footer_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        # Progress and Status
        status_frame = ctk.CTkFrame(footer_frame, fg_color="transparent")
        status_frame.pack(side="left", fill="x", expand=True, padx=(0, 20))
        
        self.label_stage = ctk.CTkLabel(status_frame, textvariable=self.stage_var, font=ctk.CTkFont(size=14, weight="bold"), text_color="#3b8ed0")
        self.label_stage.pack(anchor="w")
        
        self.label_status = ctk.CTkLabel(status_frame, textvariable=self.status_var, font=ctk.CTkFont(size=12), text_color="gray")
        self.label_status.pack(anchor="w", pady=(0, 5))
        
        self.progress_bar_widget = ctk.CTkProgressBar(status_frame, variable=self.progress_var)
        self.progress_bar_widget.pack(fill="x")
        self.progress_bar_widget.set(0)
        
        # Botões Iniciar e Parar
        btn_frame = ctk.CTkFrame(footer_frame, fg_color="transparent")
        btn_frame.pack(side="right")
        
        self.btn_preview = ctk.CTkButton(btn_frame, text="🧪 Gerar Amostra (15s)", font=ctk.CTkFont(size=14, weight="bold"), fg_color="#f0ad4e", hover_color="#ec971f", height=40, command=self.start_preview)
        self.btn_preview.pack(side="left", padx=5)

        self.btn_start = ctk.CTkButton(btn_frame, text="▶️ Iniciar Dublagem", font=ctk.CTkFont(size=14, weight="bold"), height=40, command=self.start_process)
        self.btn_start.pack(side="left", padx=5)
        
        self.btn_stop = ctk.CTkButton(btn_frame, text="⏹️ Parar", font=ctk.CTkFont(size=14, weight="bold"), fg_color="#d9534f", hover_color="#c9302c", height=40, state="disabled", command=self.stop_process)
        self.btn_stop.pack(side="left", padx=5)

    def toggle_multi_voice(self):
        if self.use_multi_voice.get():
            self.entry_speakers.configure(state="normal")
        else:
            self.entry_speakers.configure(state="disabled")

    def toggle_input_mode(self):
        mode = self.input_mode.get()
        if mode == "file":
            self.url_input_frame.pack_forget()
            self.file_input_frame.pack(fill="x", padx=15, pady=5)
        else:
            self.file_input_frame.pack_forget()
            self.url_input_frame.pack(fill="x", padx=15, pady=5)

    def select_videos_to_merge(self):
        files = filedialog.askopenfilenames(
            title="Selecionar Vídeos para Juntar (na ordem desejada)",
            filetypes=[("Arquivos de Vídeo", "*.mp4 *.avi *.mkv *.mov *.webm"), ("Todos os Arquivos", "*.*")]
        )
        if files:
            self.selected_videos_to_merge = list(files)
            self.merge_status_label.configure(text=f"{len(self.selected_videos_to_merge)} vídeo(s) selecionado(s)", text_color=("black", "white"))
            self.log(f"📁 {len(self.selected_videos_to_merge)} vídeo(s) selecionado(s) para juntar", "INFO")
    
    def merge_selected_videos(self):
        if not self.selected_videos_to_merge or len(self.selected_videos_to_merge) < 2:
            messagebox.showwarning("Aviso", "Selecione pelo menos 2 vídeos para juntar.")
            return
        
        output_path = filedialog.asksaveasfilename(
            title="Salvar Vídeo Unificado",
            defaultextension=".mp4",
            filetypes=[("Arquivos de Vídeo", "*.mp4"), ("Todos os Arquivos", "*.*")]
        )
        
        if not output_path:
            return
        
        thread = threading.Thread(target=self.run_merge_videos, args=(self.selected_videos_to_merge, output_path))
        thread.daemon = True
        thread.start()

    def run_merge_videos(self, video_paths, output_path):
        try:
            self.log(f"🔗 Iniciando merge de {len(video_paths)} vídeo(s)...", "INFO")
            from merge_videos import merge_videos
            
            success = merge_videos(video_paths, output_path, logger=self.log)
            
            if success:
                self.log(f"✅ Vídeos juntados com sucesso: {output_path}", "SUCCESS")
                self.root.after(0, lambda: messagebox.showinfo("Sucesso", f"Vídeos juntados com sucesso!\n\nArquivo salvo em:\n{output_path}"))
                self.root.after(0, lambda: self.merge_status_label.configure(text="✅ Merge concluído!", text_color="green"))
                self.selected_videos_to_merge = []
            else:
                self.log("❌ Erro ao juntar vídeos", "ERROR")
                self.root.after(0, lambda: messagebox.showerror("Erro", "Ocorreu um erro ao juntar os vídeos. Verifique os logs."))
                
        except Exception as e:
            self.log(f"❌ Erro crítico ao juntar vídeos: {str(e)}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
            self.root.after(0, lambda: messagebox.showerror("Erro", f"Erro ao juntar vídeos:\n{str(e)}"))

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Selecionar Vídeo",
            filetypes=[("Arquivos de Vídeo", "*.mp4 *.avi *.mkv *.mov *.webm"), ("Todos os Arquivos", "*.*")]
        )
        if filename:
            self.video_path.set(filename)

    def log(self, message, level="INFO"):
        self.log_queue.put((message, level))

    # --------------------------
    # Console interativo (stdin)
    # --------------------------
    def _console_init_bindings(self):
        # Enter envia a linha para o processo em execução.
        self.log_textbox.bind("<Return>", self._console_on_enter)
        # Bloqueia edição fora do prompt atual.
        self.log_textbox.bind("<KeyPress>", self._console_on_keypress)

    def _console_reset(self):
        self._console_prompt_start = None
        self._console_input_start = None
        self._console_ensure_prompt()

    def _console_ensure_prompt(self, restore_input: str = ""):
        # Insere um prompt no final e restaura eventual input digitado.
        end_idx = self.log_textbox.index("end-1c")
        self.log_textbox.insert("end", self._console_prompt + (restore_input or ""))
        self._console_prompt_start = end_idx
        self._console_input_start = self.log_textbox.index(f"{end_idx}+{len(self._console_prompt)}c")
        self.log_textbox.see("end")
        self.log_textbox.mark_set("insert", "end-1c")

    def _console_get_current_input(self) -> str:
        if self._console_input_start is None:
            return ""
        try:
            return self.log_textbox.get(self._console_input_start, "end-1c")
        except Exception:
            return ""

    def _console_write_output(self, text: str):
        # Escreve output acima do prompt, preservando o input que o usuário já digitou.
        if not text:
            return
        if not text.endswith("\n"):
            text += "\n"

        # Se por algum motivo não houver prompt, só anexa.
        if self._console_prompt_start is None or self._console_input_start is None:
            self.log_textbox.insert("end", text)
            self.log_textbox.see("end")
            self._console_ensure_prompt()
            return

        current_input = self._console_get_current_input()
        try:
            # Remove prompt+input atual e reescreve depois do output.
            self.log_textbox.delete(self._console_prompt_start, "end-1c")
        except Exception:
            pass

        self.log_textbox.insert("end", text)
        self._console_ensure_prompt(restore_input=current_input)

    def _console_on_click(self, event):
        # Mantém comportamento de terminal: clique posiciona no fim.
        try:
            self.log_textbox.mark_set("insert", "end-1c")
            self.log_textbox.see("end")
        except Exception:
            pass
        return "break"

    def _console_on_keypress(self, event):
        # Impede edição acima do prompt atual.
        if self._console_prompt_start is None or self._console_input_start is None:
            return

        try:
            insert_idx = self.log_textbox.index("insert")
            if self.log_textbox.compare(insert_idx, "<", self._console_input_start):
                self.log_textbox.mark_set("insert", "end-1c")
                self.log_textbox.see("end")
                return "break"

            # Bloqueia backspace antes do início do input.
            if event.keysym == "BackSpace":
                if self.log_textbox.compare(insert_idx, "<=", self._console_input_start):
                    return "break"
        except Exception:
            return

    def _console_on_enter(self, event):
        # Captura a linha digitada e envia ao stdin do subprocess.
        line = self._console_get_current_input().strip("\r\n")

        # Fecha a linha atual e abre novo prompt.
        self.log_textbox.insert("end", "\n")
        self._console_prompt_start = None
        self._console_input_start = None
        self._console_ensure_prompt()

        # Envia para o processo rodando (se houver).
        proc = getattr(self, "_running_process", None)
        if proc is not None and getattr(proc, "stdin", None) is not None:
            try:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
            except Exception as e:
                self._console_write_output(f"[console] Falha ao enviar entrada para o processo: {e}")
        else:
            # Se não há processo rodando, só mantém como histórico.
            pass

        return "break"

    def process_log_queue(self):
        import re
        while not self.log_queue.empty():
            msg, level = self.log_queue.get()
            
            dl_match = re.search(r"DOWNLOAD_PROGRESS:\s*(\d+\.?\d*)", msg)
            if dl_match:
                try:
                    percent = float(dl_match.group(1))
                    self.stage_var.set(f"📥 Baixando do YouTube: {percent:.1f}%")
                    # A barra de baixo vai andar de 0% até 5% (0.0 até 0.05)
                    self.progress_var.set((percent * 0.05) / 100.0)
                    continue
                except ValueError:
                    pass

            progress_match = re.search(r"PROGRESS:\s*(\d+\.?\d*)", msg)
            if progress_match:
                try:
                    percent = float(progress_match.group(1))
                    self.progress_var.set(percent / 100.0) # CTkProgressBar works with 0.0 to 1.0
                    
                    if percent < 20:
                        self.stage_var.set(f"Etapa 1/5: Transcrevendo Áudio ({percent:.1f}%)")
                    elif percent < 30:
                        self.stage_var.set(f"Etapa 2/5: Traduzindo Texto ({percent:.1f}%)")
                    elif percent < 35:
                        self.stage_var.set(f"Etapa 3/5: Processando Frases ({percent:.1f}%)")
                    elif percent < 85:
                        self.stage_var.set(f"Etapa 4/5: Dublando com IA ({percent:.1f}%)")
                    elif percent < 100:
                        self.stage_var.set(f"Etapa 5/5: Sincronizando e Renderizando ({percent:.1f}%)")
                    else:
                        self.stage_var.set("Concluído! 🎉")
                        
                    continue 
                except ValueError:
                    pass

            
            if not re.match(r"\d{4}-\d{2}-\d{2}", msg):
                from datetime import datetime
                timestamp = datetime.now().strftime("%H:%M:%S")
                full_msg = f"[{timestamp}] {msg}\n"
            else:
                full_msg = f"{msg}\n"
            
            # Simple color mapping for CustomTkinter textbox
            if level == "ERROR":
                full_msg_tagged = f"❌ {full_msg}"
            elif level == "WARNING":
                full_msg_tagged = f"⚠️ {full_msg}"
            elif level == "SUCCESS":
                full_msg_tagged = f"✅ {full_msg}"
            else:
                full_msg_tagged = full_msg

            # Escreve como console: output acima do prompt e preserva input.
            self._console_write_output(full_msg_tagged)
            
            clean_msg = msg.split("|")[-1].strip() if "|" in msg else msg
            self.status_var.set(clean_msg[:100] + "..." if len(clean_msg) > 100 else clean_msg)
            
        self.root.after(100, self.process_log_queue)

    def start_preview(self):
        self.start_process(is_preview=True)

    def start_process(self, is_preview=False):
        if self.is_running:
            return
            
        mode = self.input_mode.get()
        target = ""
        if mode == "file":
            target = self.video_path.get()
            if not target or not os.path.exists(target):
                messagebox.showerror("Erro", "Selecione um arquivo de vídeo válido.")
                return
        else:
            target = self.youtube_url.get()
            if not target:
                messagebox.showerror("Erro", "Insira uma URL do YouTube.")
                return

        # Assegura que as chaves existam mesmo se config.yaml não existir
        if "translation" not in config._config: config._config["translation"] = {}
        if "models" not in config._config: config._config["models"] = {}
        if "whisper" not in config._config["models"]: config._config["models"]["whisper"] = {}
        if "app" not in config._config: config._config["app"] = {}

        config._config["translation"]["target_language"] = self.target_lang.get()
        config._config["models"]["whisper"]["size"] = self.whisper_model.get()
        config._config["app"]["generate_subtitles"] = self.generate_subtitles.get()
        config._config["app"]["subtitle_original"] = self.subtitle_original.get()
        config._config["app"]["subtitle_translated"] = self.subtitle_translated.get()
        config._config["app"]["clean_after_completion"] = self.clean_after.get()
        config._config["app"]["keep_cut_videos"] = self.keep_cut_videos.get()
        config._config["app"]["use_multi_voice"] = self.use_multi_voice.get()
        try:
            config._config["app"]["expected_speakers"] = int(self.expected_speakers.get())
        except:
            config._config["app"]["expected_speakers"] = 2
        
        config.save()
        self.log(f"🌍 Idioma de destino: {self.target_lang.get()}", "INFO")

        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_preview.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        
        self.progress_bar_widget.set(0)
        self.progress_var.set(0.0)
        
        self.log_textbox.delete(1.0, "end")
        self._console_reset()
        if is_preview:
            self.stage_var.set("Iniciando Amostra (15s)...")
        else:
            self.stage_var.set("Iniciando...")
        
        thread = threading.Thread(target=self.run_pipeline, args=(mode, target, is_preview))
        thread.daemon = True
        thread.start()

    def stop_process(self):
        if not self.is_running:
            return
            
        if messagebox.askyesno("Confirmar", "Deseja realmente parar o processo?"):
            self.log("🛑 Parando processo...", "WARNING")
            self.is_running = False 

    def run_pipeline(self, mode, target, is_preview=False):
        try:
            if is_preview:
                self.log("🧪 Iniciando pipeline em MODO AMOSTRA (15 segundos)...", "SUCCESS")
            else:
                self.log("🚀 Iniciando pipeline de dublagem completo...", "SUCCESS")
            
            input_str = f"1\n{target}\n" if mode == "url" else f"2\n{target}\n"
            
            self.log(f"Executando transcrever.py com alvo: {target}")
            
            cmd = [sys.executable, "transcrever.py"]
            
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            # Permite que o Coqui TTS mostre o prompt de termos via stdin pipe (GUI).
            # Sem isso, o XTTS pode ser bloqueado em modo não-TTY.
            env["COQUI_TOS_ALLOW_PROMPT"] = "1"
            if is_preview:
                env["TRANSCRIBER_PREVIEW"] = "1"

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env,
                encoding='utf-8',
                errors='replace'
            )

            # Guarda referência para permitir input via console.
            self._running_process = process
            
            process.stdin.write(input_str)
            process.stdin.flush()
            
            for line in process.stdout:
                if not self.is_running:
                    process.terminate()
                    break
                line = line.strip()
                if line:
                    self.log(line)
            
            process.wait()

            # Processo terminou, desliga console stdin.
            self._running_process = None
            
            if process.returncode == 0 and self.is_running:
                self.log("✅ Processo concluído com sucesso!", "SUCCESS")
                messagebox.showinfo("Sucesso", "Dublagem concluída! Verifique a pasta do projeto.")
            elif not self.is_running:
                self.log("⚠️ Processo interrompido pelo usuário.", "WARNING")
            else:
                self.log("❌ Ocorreu um erro durante o processo.", "ERROR")
                
        except Exception as e:
            self.log(f"❌ Erro crítico: {str(e)}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
            
        finally:
            self._running_process = None
            self.cleanup_ui()

    def cleanup_ui(self):
        self.is_running = False
        self.root.after(0, self._reset_buttons)

    def _reset_buttons(self):
        self.btn_start.configure(state="normal")
        self.btn_preview.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_var.set("Pronto")
        self.stage_var.set("Aguardando início...")

if __name__ == "__main__":
    root = ctk.CTk()
    try:
        if os.path.exists("icon.ico"):
            root.iconbitmap("icon.ico")
    except:
        pass
        
    app = DubbingApp(root)
    root.mainloop()
