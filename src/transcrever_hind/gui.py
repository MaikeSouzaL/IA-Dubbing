import sys
import os
import threading
import subprocess
import queue
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox
import customtkinter as ctk
import shutil

from pathlib import Path

# Tenta importar PIL para ícone (opcional)
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from config_loader import config
from logger import setup_logger
from env_utils import save_env_value
from project_paths import pipeline_file

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
        self.batch_queue = []
        
        # Novas variáveis para funcionalidades
        self.keep_cut_videos = ctk.BooleanVar(value=config.get("app.keep_cut_videos", False))
        self.offline_mode = ctk.BooleanVar(value=config.get("app.offline_mode", False))
        self.sync_lead_ms = ctk.DoubleVar(value=float(config.get("sync.lead_ms", 60)))
        self.sync_tail_padding_ms = ctk.DoubleVar(value=float(config.get("sync.tail_padding_ms", 40)))
        self.post_action = ctk.StringVar(value="Nada")
        self.transcription_model_options = {
            "local_whisper": ["tiny", "base", "small", "medium", "large", "large-v3-turbo", "turbo"],
            "local_faster_whisper": ["tiny", "base", "small", "medium", "large-v2", "large-v3", "large-v3-turbo", "turbo"],
            "openai": ["whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"],
            "deepgram": ["nova-3", "nova-2", "enhanced", "base"],
            "assemblyai": ["universal-3-pro", "universal-2"],
            "google": ["latest_long", "latest_short", "video", "phone_call", "default"],
        }
        self.transcription_key_links = {
            "openai": "https://platform.openai.com/api-keys",
            "deepgram": "https://console.deepgram.com/project/keys",
            "assemblyai": "https://www.assemblyai.com/dashboard/api-keys",
            "google": "https://console.cloud.google.com/apis/credentials",
        }
        self.transcription_env_keys = {
            "openai": "OPENAI_API_KEY",
            "deepgram": "DEEPGRAM_API_KEY",
            "assemblyai": "ASSEMBLYAI_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        self.transcription_key_help = {
            "local_whisper": (
                "Whisper local nao precisa de chave API.\n\n"
                "1. Selecione local_whisper em Transcricao.\n"
                "2. Escolha o modelo em Modelo.\n"
                "3. Quanto maior o modelo, melhor tende a ser a precisao, mas mais VRAM/RAM e tempo ele usa.\n"
                "4. Clique em Iniciar Dublagem."
            ),
            "local_faster_whisper": (
                "Faster-Whisper local nao precisa de chave API.\n\n"
                "1. Selecione local_faster_whisper em Transcricao.\n"
                "2. Escolha large-v3-turbo ou turbo para melhor equilibrio em GPUs de 6 GB.\n"
                "3. O compute_type fica em int8_float16 por padrao para economizar VRAM.\n"
                "4. Clique em Iniciar Dublagem."
            ),
            "openai": (
                "OpenAI - como configurar\n\n"
                "1. Clique em Pegar chave openai.\n"
                "2. Entre na sua conta OpenAI.\n"
                "3. Crie uma nova API key.\n"
                "4. Cole a chave no campo Chave API.\n"
                "5. Clique em Buscar modelos.\n"
                "6. Escolha um modelo de transcricao, como whisper-1.\n"
                "7. Inicie a dublagem.\n\n"
                "Opcional: em vez de colar aqui, defina OPENAI_API_KEY no Windows."
            ),
            "deepgram": (
                "Deepgram - como configurar\n\n"
                "1. Clique em Pegar chave deepgram.\n"
                "2. Crie ou abra um projeto no console da Deepgram.\n"
                "3. Abra a area de API Keys.\n"
                "4. Crie/copiei uma chave com permissao de uso da API.\n"
                "5. Cole a chave no campo Chave API.\n"
                "6. Clique em Buscar modelos.\n"
                "7. Escolha um modelo STT, como nova-3.\n"
                "8. Inicie a dublagem.\n\n"
                "Opcional: defina DEEPGRAM_API_KEY no Windows."
            ),
            "assemblyai": (
                "AssemblyAI - como configurar\n\n"
                "1. Clique em Pegar chave assemblyai.\n"
                "2. Entre no dashboard da AssemblyAI.\n"
                "3. Copie sua API key.\n"
                "4. Cole a chave no campo Chave API.\n"
                "5. Escolha universal-3-pro ou universal-2.\n"
                "6. Inicie a dublagem.\n\n"
                "Opcional: defina ASSEMBLYAI_API_KEY no Windows."
            ),
            "google": (
                "Google Cloud Speech-to-Text - como configurar\n\n"
                "1. Clique em Pegar chave google.\n"
                "2. No Google Cloud Console, crie ou selecione um projeto.\n"
                "3. Ative a API Speech-to-Text.\n"
                "4. Ative billing no projeto, se solicitado pelo Google.\n"
                "5. Va em APIs e servicos > Credenciais.\n"
                "6. Crie uma API key.\n"
                "7. Cole a chave no campo Chave API.\n"
                "8. Escolha latest_long para videos/audios longos.\n"
                "9. Inicie a dublagem.\n\n"
                "Opcional: defina GOOGLE_API_KEY no Windows."
            ),
        }
        for provider_name in list(self.transcription_model_options.keys()):
            config_key = "faster_whisper" if provider_name == "local_faster_whisper" else provider_name
            saved_models = config.get(f"transcription.{config_key}.available_models", None)
            if saved_models:
                self.transcription_model_options[provider_name] = saved_models
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

        queue_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        queue_frame.pack(fill="x", padx=15, pady=(8, 4))

        queue_buttons = ctk.CTkFrame(queue_frame, fg_color="transparent")
        queue_buttons.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(queue_buttons, text="Fila de dublagem:").pack(side="left", padx=(0, 10))
        ctk.CTkButton(queue_buttons, text="+ Link atual", width=105, command=self.add_current_input_to_queue).pack(side="left", padx=4)
        ctk.CTkButton(queue_buttons, text="+ Arquivos", width=100, command=self.add_files_to_queue).pack(side="left", padx=4)
        ctk.CTkButton(queue_buttons, text="Remover", width=90, command=self.remove_selected_queue_item).pack(side="left", padx=4)
        ctk.CTkButton(queue_buttons, text="Limpar", width=80, command=self.clear_queue).pack(side="left", padx=4)

        ctk.CTkLabel(queue_buttons, text="Ao terminar:").pack(side="left", padx=(22, 6))
        self.combo_post_action = ctk.CTkComboBox(
            queue_buttons,
            variable=self.post_action,
            values=["Nada", "Desligar", "Hibernar"],
            width=120,
        )
        self.combo_post_action.pack(side="left")

        self.queue_listbox = tk.Listbox(queue_frame, height=4, activestyle="dotbox")
        self.queue_listbox.pack(fill="x", expand=True)
        
        # Configurações Rápidas
        config_frame = ctk.CTkFrame(self.main_frame)
        config_frame.pack(fill="x", pady=(0, 20), ipady=10)
        
        ctk.CTkLabel(config_frame, text="Configurações Rápidas", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        grid_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        grid_frame.pack(fill="x", padx=15, pady=5)
        
        # Linha 1
        self.label_whisper_model = ctk.CTkLabel(grid_frame, text="Modelo Whisper:")
        self.label_whisper_model.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=10)
        self.whisper_model = ctk.StringVar(value=config.get("models.whisper.size", "medium"))
        models = ["tiny", "base", "small", "medium", "large", "large-v3-turbo", "turbo"]
        self.combo_whisper_model = ctk.CTkComboBox(
            grid_frame,
            variable=self.whisper_model,
            values=models,
            width=140,
            command=lambda value: self.transcription_model.set(value) if self.transcription_provider.get() == "local_whisper" else None,
        )
        self.combo_whisper_model.grid(row=0, column=1, sticky="w", padx=0, pady=10)

        ctk.CTkLabel(grid_frame, text="Transcricao:").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=10)
        self.transcription_provider = ctk.StringVar(value=config.get("transcription.provider", "local_whisper"))
        providers = ["local_whisper", "local_faster_whisper", "openai", "deepgram", "assemblyai", "google"]
        self.combo_transcription_provider = ctk.CTkComboBox(
            grid_frame,
            variable=self.transcription_provider,
            values=providers,
            width=150,
            command=lambda _value: self.on_transcription_provider_changed(),
        )
        self.combo_transcription_provider.grid(row=4, column=1, sticky="w", padx=0, pady=10)

        ctk.CTkLabel(grid_frame, text="Modelo:").grid(row=4, column=2, sticky="w", padx=(30, 10), pady=10)
        self.transcription_model = ctk.StringVar(value=self.get_current_transcription_model())
        self.combo_transcription_model = ctk.CTkComboBox(
            grid_frame,
            variable=self.transcription_model,
            values=self.transcription_model_options.get(self.transcription_provider.get(), models),
            width=180,
            command=lambda value: self.on_transcription_model_changed(value),
        )
        self.combo_transcription_model.grid(row=4, column=3, sticky="w", padx=0, pady=10)

        self.btn_fetch_models = ctk.CTkButton(
            grid_frame,
            text="Buscar modelos",
            width=130,
            command=self.fetch_transcription_models,
        )
        self.btn_fetch_models.grid(row=4, column=4, sticky="w", padx=(15, 0), pady=10)

        ctk.CTkLabel(grid_frame, text="Chave API:").grid(row=5, column=0, sticky="w", padx=(0, 10), pady=10)
        self.transcription_api_key = ctk.StringVar(value=self.get_current_transcription_api_key())
        self.entry_transcription_api_key = ctk.CTkEntry(
            grid_frame,
            textvariable=self.transcription_api_key,
            width=380,
            show="*",
            placeholder_text="Opcional se ja estiver em variavel de ambiente",
        )
        self.entry_transcription_api_key.grid(row=5, column=1, columnspan=3, sticky="we", padx=0, pady=10)
        self.entry_transcription_api_key.bind("<FocusOut>", lambda _event: self.save_transcription_settings())
        self.link_transcription_api_key = ctk.CTkLabel(
            grid_frame,
            text="Abrir pagina da chave",
            text_color="#3b8ed0",
            cursor="hand2",
        )
        self.link_transcription_api_key.grid(row=5, column=4, sticky="w", padx=(15, 0), pady=10)
        self.link_transcription_api_key.bind("<Button-1>", lambda _event: self.open_transcription_key_page())

        self.btn_transcription_help = ctk.CTkButton(
            grid_frame,
            text="Como configurar",
            width=130,
            command=self.show_transcription_key_help,
        )
        self.btn_transcription_help.grid(row=6, column=1, sticky="w", padx=0, pady=(0, 10))

        self.btn_save_transcription = ctk.CTkButton(
            grid_frame,
            text="Salvar",
            width=100,
            fg_color="#28a745",
            hover_color="#218838",
            command=self.save_transcription_settings_clicked,
        )
        self.btn_save_transcription.grid(row=6, column=2, sticky="w", padx=(15, 0), pady=(0, 10))
        self.btn_test_transcription_api = ctk.CTkButton(
            grid_frame,
            text="Testar API",
            width=110,
            command=self.test_transcription_api,
        )
        self.btn_test_transcription_api.grid(row=6, column=3, sticky="w", padx=(15, 0), pady=(0, 10))
        self.update_transcription_provider_fields()
        self.label_whisper_model.grid_remove()
        self.combo_whisper_model.grid_remove()
        
        ctk.CTkLabel(grid_frame, text="Idioma Destino:").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=10)
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
        
        ctk.CTkComboBox(grid_frame, variable=self.target_lang, values=lang_codes, width=100).grid(row=0, column=1, sticky="w", padx=0, pady=10)
        
        self.clean_after = ctk.BooleanVar(value=config.get("app.clean_after_completion", True))
        ctk.CTkCheckBox(grid_frame, text="Limpar temporários", variable=self.clean_after).grid(row=0, column=2, sticky="w", padx=(30, 0), pady=10)
        ctk.CTkCheckBox(
            grid_frame,
            text="Modo offline",
            variable=self.offline_mode,
            command=self.on_offline_mode_changed,
        ).grid(row=0, column=3, sticky="w", padx=(30, 0), pady=10)
        
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
        
        self.lbl_bg_volume_text = ctk.CTkLabel(adv_frame, text="Vol Fundo:")
        self.lbl_bg_volume_text.pack(side="left", padx=(15, 5))
        
        self.bg_volume = ctk.DoubleVar(value=float(config.get("audio.bg_volume", -6.0)))
        
        def update_bg_label(value):
            self.lbl_bg_volume_val.configure(text=f"{float(value):.1f} dB")
            
        self.slider_bg_volume = ctk.CTkSlider(
            adv_frame, from_=-30, to=10, number_of_steps=40, 
            variable=self.bg_volume, command=update_bg_label, width=120
        )
        self.slider_bg_volume.pack(side="left", padx=(0, 5))
        
        self.lbl_bg_volume_val = ctk.CTkLabel(adv_frame, text=f"{self.bg_volume.get():.1f} dB", width=50, anchor="w")
        self.lbl_bg_volume_val.pack(side="left")
        
        self.toggle_multi_voice()

        sync_frame = ctk.CTkFrame(grid_frame, fg_color="transparent")
        sync_frame.grid(row=7, column=0, columnspan=5, sticky="we", pady=(5, 10))

        ctk.CTkLabel(sync_frame, text="Sincronizacao da fala:", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(0, 15))

        ctk.CTkLabel(sync_frame, text="Adiantar").pack(side="left", padx=(0, 5))
        self.slider_sync_lead = ctk.CTkSlider(
            sync_frame,
            from_=0,
            to=200,
            number_of_steps=20,
            variable=self.sync_lead_ms,
            command=lambda value: self.lbl_sync_lead_val.configure(text=f"{int(float(value))} ms"),
            width=110,
        )
        self.slider_sync_lead.pack(side="left")
        self.lbl_sync_lead_val = ctk.CTkLabel(sync_frame, text=f"{int(self.sync_lead_ms.get())} ms", width=55, anchor="w")
        self.lbl_sync_lead_val.pack(side="left", padx=(5, 15))

        ctk.CTkLabel(sync_frame, text="Folga final").pack(side="left", padx=(0, 5))
        self.slider_sync_tail = ctk.CTkSlider(
            sync_frame,
            from_=0,
            to=250,
            number_of_steps=25,
            variable=self.sync_tail_padding_ms,
            command=lambda value: self.lbl_sync_tail_val.configure(text=f"{int(float(value))} ms"),
            width=110,
        )
        self.slider_sync_tail.pack(side="left")
        self.lbl_sync_tail_val = ctk.CTkLabel(sync_frame, text=f"{int(self.sync_tail_padding_ms.get())} ms", width=55, anchor="w")
        self.lbl_sync_tail_val.pack(side="left", padx=(5, 15))
        ctk.CTkButton(sync_frame, text="Salvar", width=70, command=self.save_sync_settings_clicked).pack(side="left", padx=(15, 0))
        
        # Juntar Vídeos
        merge_frame = ctk.CTkFrame(self.main_frame)
        merge_frame.pack(fill="x", pady=(0, 20), ipady=10)
        
        ctk.CTkLabel(merge_frame, text="🔗 Juntar Vídeos Dublados", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=(10, 5))
        
        merge_inner = ctk.CTkFrame(merge_frame, fg_color="transparent")
        merge_inner.pack(fill="x", padx=15, pady=5)
        
        ctk.CTkLabel(merge_inner, text="Selecione os vídeos na ordem desejada:").pack(side="left", padx=(0, 15))
        ctk.CTkButton(merge_inner, text="📁 Selecionar", command=self.select_videos_to_merge, width=120).pack(side="left", padx=5)
        ctk.CTkButton(merge_inner, text="🔗 Juntar", command=self.merge_selected_videos, fg_color="#28a745", hover_color="#218838", width=100).pack(side="left", padx=5)
        ctk.CTkButton(merge_inner, text="Abrir pasta", command=self.open_output_folder, width=110).pack(side="left", padx=5)
        ctk.CTkButton(merge_inner, text="Checar dependencias", command=self.check_dependencies, width=150).pack(side="left", padx=5)
        ctk.CTkButton(merge_inner, text="Atualizar yt-dlp", command=self.update_ytdlp, width=130).pack(side="left", padx=5)
        
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
        
        self.btn_start = ctk.CTkButton(btn_frame, text="▶️ Iniciar Dublagem", font=ctk.CTkFont(size=14, weight="bold"), height=40, command=self.start_process)
        self.btn_start.pack(side="left", padx=5)

        self.btn_resume = ctk.CTkButton(btn_frame, text="⏩ Continuar Dublagem", font=ctk.CTkFont(size=14, weight="bold"), fg_color="#5a6fd6", hover_color="#4a5fc6", height=40, command=self.resume_process)
        self.btn_resume.pack(side="left", padx=5)
        
        self.btn_stop = ctk.CTkButton(btn_frame, text="⏹️ Parar", font=ctk.CTkFont(size=14, weight="bold"), fg_color="#d9534f", hover_color="#c9302c", height=40, state="disabled", command=self.stop_process)
        self.btn_stop.pack(side="left", padx=5)

    def get_current_transcription_model(self):
        provider = self.transcription_provider.get() if hasattr(self, "transcription_provider") else config.get("transcription.provider", "local_whisper")
        if provider == "local_whisper":
            return config.get("models.whisper.size", "medium")
        if provider == "local_faster_whisper":
            return config.get("transcription.faster_whisper.model", config.get("models.faster_whisper.size", "large-v3-turbo"))
        return config.get(f"transcription.{provider}.model", (self.transcription_model_options.get(provider) or [""])[0])

    def get_current_transcription_api_key(self):
        provider = self.transcription_provider.get() if hasattr(self, "transcription_provider") else config.get("transcription.provider", "local_whisper")
        if provider in ("local_whisper", "local_faster_whisper"):
            return ""
        return config.get(f"transcription.{provider}.api_key", "")

    def update_transcription_provider_fields(self):
        if not hasattr(self, "combo_transcription_model"):
            return
        provider = self.transcription_provider.get()
        models = self.transcription_model_options.get(provider, [])
        if provider == "local_whisper":
            current_model = config.get("models.whisper.size", "medium")
        elif provider == "local_faster_whisper":
            current_model = config.get("transcription.faster_whisper.model", config.get("models.faster_whisper.size", "large-v3-turbo"))
        else:
            current_model = config.get(f"transcription.{provider}.model", None)
        if current_model not in models and models:
            current_model = models[0]
        self.transcription_model.set(current_model or "")
        self.combo_transcription_model.configure(values=models, state="normal")

        if provider in ("local_whisper", "local_faster_whisper"):
            self.transcription_api_key.set("")
            self.entry_transcription_api_key.configure(state="disabled", placeholder_text="Transcricao local nao usa chave API")
            self.link_transcription_api_key.configure(text="Transcricao local nao usa chave", text_color="gray")
            self.btn_transcription_help.configure(text="Sobre o motor local")
            if provider == "local_whisper":
                self.whisper_model.set(self.transcription_model.get())
        else:
            self.transcription_api_key.set(config.get(f"transcription.{provider}.api_key", ""))
            self.entry_transcription_api_key.configure(state="normal", placeholder_text="Cole a chave API ou use variavel de ambiente")
            self.link_transcription_api_key.configure(text=f"Pegar chave {provider}", text_color="#3b8ed0")
            self.btn_transcription_help.configure(text="Como configurar")

    def on_transcription_provider_changed(self):
        self.update_transcription_provider_fields()
        self.save_transcription_settings()

    def on_transcription_model_changed(self, value):
        if self.transcription_provider.get() == "local_whisper":
            self.whisper_model.set(value)
        self.save_transcription_settings()

    def save_transcription_settings(self):
        if not hasattr(self, "transcription_provider") or not hasattr(self, "transcription_model"):
            return
        if "models" not in config._config:
            config._config["models"] = {}
        if "whisper" not in config._config["models"]:
            config._config["models"]["whisper"] = {}
        if "transcription" not in config._config:
            config._config["transcription"] = {}
        for provider_name in ["faster_whisper", "openai", "deepgram", "assemblyai", "google"]:
            if provider_name not in config._config["transcription"]:
                config._config["transcription"][provider_name] = {}

        provider = self.transcription_provider.get()
        model = self.transcription_model.get().strip()
        config._config["transcription"]["provider"] = provider
        if provider == "local_whisper":
            config._config["models"]["whisper"]["size"] = model or self.whisper_model.get()
            self.whisper_model.set(config._config["models"]["whisper"]["size"])
        elif provider == "local_faster_whisper":
            if "faster_whisper" not in config._config["models"]:
                config._config["models"]["faster_whisper"] = {}
            selected = model or config._config["models"]["faster_whisper"].get("size", "large-v3-turbo")
            config._config["models"]["faster_whisper"]["size"] = selected
            config._config["transcription"]["faster_whisper"]["model"] = selected
        else:
            config._config["transcription"][provider]["model"] = model
            api_key = self.transcription_api_key.get().strip()
            env_key = self.transcription_env_keys.get(provider)
            if env_key:
                save_env_value(env_key, api_key)
            config._config["transcription"][provider]["api_key"] = ""
        config.save()

    def save_transcription_settings_clicked(self):
        self.save_transcription_settings()
        provider = self.transcription_provider.get()
        model = self.transcription_model.get()
        self.log(f"Configuracao de transcricao salva: {provider} / {model}", "SUCCESS")

    def save_sync_settings(self):
        if "sync" not in config._config:
            config._config["sync"] = {}
        try:
            config._config["sync"]["lead_ms"] = int(float(self.sync_lead_ms.get()))
        except Exception:
            config._config["sync"]["lead_ms"] = 60
        try:
            config._config["sync"]["tail_padding_ms"] = int(float(self.sync_tail_padding_ms.get()))
        except Exception:
            config._config["sync"]["tail_padding_ms"] = 40

    def save_sync_settings_clicked(self):
        self.save_sync_settings()
        config.save()
        self.log(
            f"Sincronizacao salva: adiantar {config._config['sync']['lead_ms']}ms, "
            f"folga {config._config['sync']['tail_padding_ms']}ms",
            "SUCCESS",
        )

    def on_offline_mode_changed(self):
        if "app" not in config._config:
            config._config["app"] = {}
        config._config["app"]["offline_mode"] = self.offline_mode.get()
        if self.offline_mode.get() and self.transcription_provider.get() not in ("local_whisper", "local_faster_whisper"):
            self.transcription_provider.set("local_whisper")
            self.update_transcription_provider_fields()
            self.save_transcription_settings()
            self.log("Modo offline ativado: transcricao alterada para local_whisper.", "WARNING")
        config.save()

    def open_transcription_key_page(self):
        provider = self.transcription_provider.get()
        url = self.transcription_key_links.get(provider)
        if not url:
            return
        webbrowser.open(url)

    def show_transcription_key_help(self):
        provider = self.transcription_provider.get()
        help_text = self.transcription_key_help.get(provider, "Nenhum passo a passo disponivel para este provedor.")
        window = ctk.CTkToplevel(self.root)
        window.title(f"Como configurar {provider}")
        window.geometry("620x520")
        window.transient(self.root)
        window.grab_set()

        frame = ctk.CTkFrame(window)
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        title = ctk.CTkLabel(
            frame,
            text=f"Configurar {provider}",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title.pack(anchor="w", padx=12, pady=(12, 8))

        text = ctk.CTkTextbox(frame, wrap="word", height=360)
        text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        text.insert("1.0", help_text)
        text.configure(state="disabled")

        button_frame = ctk.CTkFrame(frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=12, pady=(0, 12))
        if provider in self.transcription_key_links:
            ctk.CTkButton(
                button_frame,
                text="Abrir pagina da chave",
                command=self.open_transcription_key_page,
                width=160,
            ).pack(side="left")
        ctk.CTkButton(button_frame, text="Fechar", command=window.destroy, width=100).pack(side="right")

    def fetch_transcription_models(self):
        provider = self.transcription_provider.get()
        api_key = self.transcription_api_key.get().strip() if hasattr(self, "transcription_api_key") else ""
        self.btn_fetch_models.configure(state="disabled", text="Buscando...")
        self.log(f"Buscando modelos disponiveis para {provider}...", "INFO")

        thread = threading.Thread(target=self._fetch_transcription_models_worker, args=(provider, api_key))
        thread.daemon = True
        thread.start()

    def test_transcription_api(self):
        provider = self.transcription_provider.get()
        if provider in ("local_whisper", "local_faster_whisper"):
            messagebox.showinfo("Teste", "Transcricao local nao usa API. Basta os modelos locais estarem disponiveis.")
            return
        self.save_transcription_settings()
        self.btn_test_transcription_api.configure(state="disabled", text="Testando...")
        thread = threading.Thread(target=self._test_transcription_api_worker, args=(provider,))
        thread.daemon = True
        thread.start()

    def _test_transcription_api_worker(self, provider):
        try:
            from transcription_providers import list_available_models
            models = list_available_models(provider, api_key=self.transcription_api_key.get().strip() or None)
            self.root.after(0, lambda: self._finish_test_transcription_api(provider, True, f"Conexao OK. {len(models)} modelo(s) disponiveis."))
        except Exception as e:
            self.root.after(0, lambda: self._finish_test_transcription_api(provider, False, str(e)))

    def _finish_test_transcription_api(self, provider, ok, message):
        self.btn_test_transcription_api.configure(state="normal", text="Testar API")
        if ok:
            self.log(f"API {provider} testada com sucesso: {message}", "SUCCESS")
            messagebox.showinfo("Teste de API", message)
        else:
            self.log(f"Falha no teste da API {provider}: {message}", "ERROR")
            messagebox.showerror("Teste de API", message)

    def _fetch_transcription_models_worker(self, provider, api_key):
        try:
            from transcription_providers import list_available_models
            models = list_available_models(provider, api_key=api_key or None)
            self.root.after(0, lambda: self._apply_fetched_transcription_models(provider, models))
        except Exception as e:
            self.root.after(0, lambda: self._finish_fetch_transcription_models_error(str(e)))

    def _apply_fetched_transcription_models(self, provider, models):
        models = [m for m in models if m]
        if not models:
            self._finish_fetch_transcription_models_error("Nenhum modelo encontrado.")
            return
        current = self.transcription_model.get()
        self.transcription_model_options[provider] = models
        self.combo_transcription_model.configure(values=models)
        self.transcription_model.set(current if current in models else models[0])
        if "transcription" not in config._config:
            config._config["transcription"] = {}
        config_key = "faster_whisper" if provider == "local_faster_whisper" else provider
        if config_key not in config._config["transcription"]:
            config._config["transcription"][config_key] = {}
        config._config["transcription"][config_key]["available_models"] = models
        config.save()
        if provider == "local_whisper":
            self.whisper_model.set(self.transcription_model.get())
        self.btn_fetch_models.configure(state="normal", text="Buscar modelos")
        self.log(f"{len(models)} modelo(s) encontrados para {provider}.", "SUCCESS")

    def _finish_fetch_transcription_models_error(self, error):
        self.btn_fetch_models.configure(state="normal", text="Buscar modelos")
        self.log(f"Falha ao buscar modelos: {error}", "ERROR")
        messagebox.showwarning("Modelos", f"Nao foi possivel buscar modelos automaticamente.\n\n{error}")

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

    def open_output_folder(self):
        try:
            from job_manager import load_current_job
            state = load_current_job()
            path = state.get("job_dir") if state else os.getcwd()
        except Exception:
            path = os.getcwd()
        if not os.path.isdir(path):
            path = os.getcwd()
        os.startfile(path)

    def check_dependencies(self):
        try:
            import pyannote.audio  # noqa: F401
            pyannote_ok = True
        except Exception:
            pyannote_ok = False
        checks = {
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": shutil.which("ffprobe") is not None,
            "demucs": shutil.which("demucs") is not None,
            "yt-dlp": shutil.which("yt-dlp") is not None,
            "node": shutil.which("node") is not None,
            "deno": shutil.which("deno") is not None,
            "pyannote.audio": pyannote_ok,
        }
        missing = [name for name, ok in checks.items() if not ok]
        for name, ok in checks.items():
            self.log(f"Dependencia {name}: {'OK' if ok else 'faltando'}", "SUCCESS" if ok else "WARNING")
        if not (os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or config.get("models.pyannote.hf_token", None)):
            self.log("Token HuggingFace para diarizacao: nao configurado (necessario para multi-voz com pyannote).", "WARNING")
        
        if missing:
            if "deno" in missing:
                resposta = messagebox.askyesno(
                    "Dependências faltando",
                    f"Faltam as seguintes dependências: {', '.join(missing)}\n\nDeseja instalar o Deno automaticamente pelo PowerShell agora?"
                )
                if resposta:
                    self.install_deno_automatically()
            else:
                messagebox.showwarning("Dependencias", "Faltando: " + ", ".join(missing))
        else:
            messagebox.showinfo("Dependencias", "Todas as dependencias principais foram encontradas.")

    def install_deno_automatically(self):
        self.log("Iniciando instalação do Deno via PowerShell...", "INFO")
        def worker():
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://deno.land/install.ps1 | iex"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    self.log("Deno instalado com sucesso! Reinicie o app para aplicar o PATH.", "SUCCESS")
                    self.root.after(0, lambda: messagebox.showinfo("Deno Instalado", "Deno instalado com sucesso!\n\nFeche e abra novamente essa ferramenta para que o sistema reconheça a instalação (PATH)."))
                else:
                    self.log(f"Falha ao instalar o Deno: {result.stderr}", "ERROR")
                    self.root.after(0, lambda: messagebox.showerror("Erro", "Falha ao instalar o Deno automaticamente.\nVerifique os logs."))
            except Exception as e:
                self.log(f"Erro na instalação automática: {e}", "ERROR")
                self.root.after(0, lambda: messagebox.showerror("Erro", f"Exceção ao instalar o Deno:\n{e}"))

        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()

    def update_ytdlp(self):
        if self.offline_mode.get():
            messagebox.showwarning("Modo offline", "Nao e possivel atualizar yt-dlp no modo offline.")
            return
        thread = threading.Thread(target=self._update_ytdlp_worker)
        thread.daemon = True
        thread.start()

    def _update_ytdlp_worker(self):
        self.log("Atualizando yt-dlp...", "INFO")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                self.log("yt-dlp atualizado com sucesso.", "SUCCESS")
            else:
                self.log(f"Falha ao atualizar yt-dlp: {result.stderr[-800:]}", "ERROR")
        except Exception as e:
            self.log(f"Erro ao atualizar yt-dlp: {e}", "ERROR")

    def estimate_api_cost_message(self, target):
        provider = self.transcription_provider.get()
        rates = {
            "openai": "depende do modelo; confira a pagina de precos da OpenAI",
            "deepgram": "depende do plano/modelo; confira a pagina de precos da Deepgram",
            "assemblyai": "depende do modelo; confira a pagina de precos da AssemblyAI",
            "google": "depende da duracao e modelo; confira os precos do Google Cloud Speech-to-Text",
        }
        duration_text = "duracao desconhecida"
        if self.input_mode.get() == "file" and os.path.isfile(target):
            try:
                from long_video.utils import ffprobe_duration
                seconds = ffprobe_duration(target)
                if seconds:
                    duration_text = f"{seconds/60:.1f} minutos"
            except Exception:
                pass
        return (
            f"Voce selecionou transcricao externa: {provider}.\n"
            f"Estimativa: {duration_text}.\n"
            f"Custo: {rates.get(provider, 'verifique o provedor')}.\n"
            "Se a API falhar, o sistema tenta fallback com Whisper local."
        )
    
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

    def _refresh_queue_listbox(self):
        self.queue_listbox.delete(0, "end")
        for index, item in enumerate(self.batch_queue, 1):
            label = "YouTube" if item["mode"] == "url" else "Arquivo"
            self.queue_listbox.insert("end", f"{index:02d}. [{label}] {item['target']}")

    def add_current_input_to_queue(self):
        mode = self.input_mode.get()
        target = self.youtube_url.get().strip() if mode == "url" else self.video_path.get().strip()
        if not target:
            messagebox.showwarning("Fila", "Informe um link ou arquivo antes de adicionar.")
            return
        if mode == "file" and not os.path.exists(target):
            messagebox.showwarning("Fila", "Arquivo nao encontrado.")
            return
        self.batch_queue.append({"mode": mode, "target": target})
        self._refresh_queue_listbox()
        self.log(f"Adicionado a fila: {target}", "SUCCESS")

    def add_files_to_queue(self):
        files = filedialog.askopenfilenames(
            title="Adicionar videos a fila",
            filetypes=[("Arquivos de Video", "*.mp4 *.avi *.mkv *.mov *.webm"), ("Todos os Arquivos", "*.*")]
        )
        for filename in files:
            self.batch_queue.append({"mode": "file", "target": filename})
        if files:
            self._refresh_queue_listbox()
            self.log(f"{len(files)} arquivo(s) adicionados a fila.", "SUCCESS")

    def remove_selected_queue_item(self):
        selection = self.queue_listbox.curselection()
        if not selection:
            return
        for index in reversed(selection):
            del self.batch_queue[index]
        self._refresh_queue_listbox()

    def clear_queue(self):
        self.batch_queue.clear()
        self._refresh_queue_listbox()

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

    def start_process(self):
        if self.is_running:
            return
            
        mode = self.input_mode.get()
        target = ""
        queue_items = list(self.batch_queue)
        if queue_items:
            if self.offline_mode.get() and any(item["mode"] == "url" for item in queue_items):
                messagebox.showerror("Modo offline", "No modo offline, a fila deve ter apenas arquivos locais.")
                return
            missing = [item["target"] for item in queue_items if item["mode"] == "file" and not os.path.exists(item["target"])]
            if missing:
                messagebox.showerror("Arquivo nao encontrado", "Alguns arquivos da fila nao existem:\n\n" + "\n".join(missing[:5]))
                return
            mode = queue_items[0]["mode"]
            target = queue_items[0]["target"]
            self.input_mode.set(mode)
            if mode == "file":
                self.video_path.set(target)
            else:
                self.youtube_url.set(target)
            self.toggle_input_mode()
        if self.offline_mode.get() and mode == "url":
            messagebox.showerror("Modo offline", "No modo offline, use um arquivo local. URLs do YouTube precisam de internet.")
            return
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
        provider = self.transcription_provider.get()
        if provider not in ("local_whisper", "local_faster_whisper"):
            estimate = self.estimate_api_cost_message(target)
            if estimate and not messagebox.askyesno("Estimativa de API", estimate + "\n\nDeseja continuar?"):
                return

        if "translation" not in config._config: config._config["translation"] = {}
        if "models" not in config._config: config._config["models"] = {}
        if "whisper" not in config._config["models"]: config._config["models"]["whisper"] = {}
        if "app" not in config._config: config._config["app"] = {}
        if "transcription" not in config._config: config._config["transcription"] = {}
        for provider_name in ["faster_whisper", "openai", "deepgram", "assemblyai", "google"]:
            if provider_name not in config._config["transcription"]:
                config._config["transcription"][provider_name] = {}

        selected_provider = self.transcription_provider.get()
        selected_model = self.transcription_model.get().strip()
        config._config["translation"]["target_language"] = self.target_lang.get()
        if selected_provider == "local_whisper":
            config._config["models"]["whisper"]["size"] = selected_model or self.whisper_model.get()
            self.whisper_model.set(config._config["models"]["whisper"]["size"])
        elif selected_provider == "local_faster_whisper":
            if "faster_whisper" not in config._config["models"]:
                config._config["models"]["faster_whisper"] = {}
            selected_model = selected_model or config._config["models"]["faster_whisper"].get("size", "large-v3-turbo")
            config._config["models"]["faster_whisper"]["size"] = selected_model
            config._config["transcription"]["faster_whisper"]["model"] = selected_model
        else:
            config._config["models"]["whisper"]["size"] = self.whisper_model.get()
            config._config["transcription"][selected_provider]["model"] = selected_model
            api_key = self.transcription_api_key.get().strip()
            env_key = self.transcription_env_keys.get(selected_provider)
            if env_key:
                save_env_value(env_key, api_key)
            config._config["transcription"][selected_provider]["api_key"] = ""
        config._config["transcription"]["provider"] = selected_provider
        config._config["app"]["generate_subtitles"] = self.generate_subtitles.get()
        config._config["app"]["subtitle_original"] = self.subtitle_original.get()
        config._config["app"]["subtitle_translated"] = self.subtitle_translated.get()
        config._config["app"]["offline_mode"] = self.offline_mode.get()
        config._config["app"]["clean_after_completion"] = self.clean_after.get()
        config._config["app"]["keep_cut_videos"] = self.keep_cut_videos.get()
        config._config["app"]["use_multi_voice"] = self.use_multi_voice.get()
        try:
            config._config["app"]["expected_speakers"] = int(self.expected_speakers.get())
        except:
            config._config["app"]["expected_speakers"] = 2
            
        if "audio" not in config._config: config._config["audio"] = {}
        try:
            config._config["audio"]["bg_volume"] = float(self.bg_volume.get())
        except:
            config._config["audio"]["bg_volume"] = -6.0

        self.save_sync_settings()
        
        config.save()
        self.log(f"Modelo de transcricao: {self.transcription_model.get()}", "INFO")
        self.log(f"Motor de transcricao: {self.transcription_provider.get()}", "INFO")
        self.log(f"🌍 Idioma de destino: {self.target_lang.get()}", "INFO")
        self.log(
            f"Sincronizacao: adiantar {config._config['sync']['lead_ms']}ms, "
            f"folga {config._config['sync']['tail_padding_ms']}ms",
            "INFO",
        )

        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_bar_widget.set(0)
        self.progress_var.set(0.0)
        self.log_textbox.delete(1.0, "end")
        self._console_reset()
        self.stage_var.set("Iniciando...")
        
        if queue_items:
            thread = threading.Thread(target=self.run_batch_pipeline, args=(queue_items,))
        else:
            thread = threading.Thread(target=self.run_pipeline, args=(mode, target))
        thread.daemon = True
        thread.start()

    def stop_process(self):
        if not self.is_running:
            return
            
        if messagebox.askyesno("Confirmar", "Deseja realmente parar o processo?"):
            self.log("🛑 Parando processo...", "WARNING")
            self.is_running = False
            proc = getattr(self, "_running_process", None)
            if proc is not None and proc.poll() is None:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, text=True)
                    self.log("Processo e subprocessos encerrados.", "WARNING")
                except Exception as e:
                    self.log(f"Falha ao encerrar subprocessos: {e}", "ERROR")

    def resume_process(self):
        """Continua a dublagem de onde parou (pula transcrição/tradução, só TTS + sync)."""
        if self.is_running:
            return
        self.save_sync_settings()
        config.save()

        # Verifica pré-requisitos
        frases_path = pipeline_file("frases_pt.json")
        if not os.path.isfile(frases_path):
            messagebox.showerror(
                "Arquivo não encontrado",
                "Não foi encontrado 'frases_pt.json'.\n"
                "Execute a dublagem completa primeiro para gerar a transcrição."
            )
            return

        # Conta frases já prontas vs total
        audios_dir = config.get("paths.tts_output_dir", "data/work/audios_frases_pt")
        done = 0
        total = 0
        try:
            import json
            with open(frases_path, "r", encoding="utf-8") as f:
                frases = json.load(f)
            total = len(frases)
            if os.path.isdir(audios_dir):
                done = len([x for x in os.listdir(audios_dir) if x.startswith("frase_") and x.endswith(".wav")])
        except Exception:
            pass

        if done >= total and total > 0:
            # Todas as frases já foram geradas — vai direto para sincronização
            msg = (
                f"Todas as {total} frases já foram geradas!\n\n"
                "Deseja executar apenas a sincronização e finalização do vídeo?"
            )
        else:
            msg = (
                f"Continuar dublagem de onde parou?\n\n"
                f"• Frases prontas: {done}/{total}\n"
                f"• Frases restantes: {max(0, total - done)}\n\n"
                "As frases já geradas serão puladas automaticamente."
            )

        if not messagebox.askyesno("Continuar Dublagem", msg):
            return

        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_bar_widget.set(0)
        self.progress_var.set(0.0)
        self.log_textbox.delete(1.0, "end")
        self._console_reset()
        self.stage_var.set("Continuando dublagem...")

        thread = threading.Thread(target=self.run_resume_pipeline)
        thread.daemon = True
        thread.start()

    def run_resume_pipeline(self):
        """Executa apenas dublar_frases_pt.py + sincronizar_e_juntar.py."""
        try:
            self.log("⏩ Retomando pipeline: TTS + Sincronização...", "SUCCESS")

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["COQUI_TOS_ALLOW_PROMPT"] = "1"

            # Etapa 1: Dublar frases (pula as que já existem)
            self.log("🎤 Etapa: Dublando frases restantes...", "INFO")
            self.stage_var.set("Etapa 4/5: Dublando com IA...")

            process = subprocess.Popen(
                [sys.executable, str(Path("scripts") / "dublar_frases_pt.py")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
            self._running_process = process

            for line in process.stdout:
                if not self.is_running:
                    process.terminate()
                    break
                line = line.strip()
                if line:
                    self.log(line)

            process.wait()
            self._running_process = None

            if not self.is_running:
                self.log("⚠️ Processo interrompido pelo usuário.", "WARNING")
                return

            if process.returncode != 0:
                self.log(f"❌ dublar_frases_pt.py encerrou com erro (código {process.returncode}).", "ERROR")
                return

            self.log("✅ Dublagem concluída!", "SUCCESS")

        except Exception as e:
            self.log(f"❌ Erro crítico ao retomar: {str(e)}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
        finally:
            self._running_process = None
            self.cleanup_ui()

    def resume_process(self):
        """Continua automaticamente da etapa mais segura encontrada."""
        if self.is_running:
            return
        self.save_sync_settings()
        config.save()

        try:
            from job_manager import infer_resume_step
            resume_step = infer_resume_step()
        except Exception:
            resume_step = "tts" if os.path.isfile(pipeline_file("frases_pt.json")) else "full"

        if resume_step == "full":
            messagebox.showerror(
                "Nada para continuar",
                "Nao encontrei transcricao.json nem frases_pt.json para retomar.\n"
                "Inicie uma dublagem completa primeiro."
            )
            return

        done = 0
        total = 0
        try:
            import json
            with open(pipeline_file("frases_pt.json"), "r", encoding="utf-8") as f:
                frases = json.load(f)
            total = len(frases)
            audios_dir = config.get("paths.tts_output_dir", "data/work/audios_frases_pt")
            if os.path.isdir(audios_dir):
                done = len([x for x in os.listdir(audios_dir) if x.startswith("frase_") and x.endswith(".wav")])
        except Exception:
            pass

        labels = {
            "translate": "traducao + frases + TTS + sincronizacao",
            "tts": "TTS + sincronizacao",
            "sync": "sincronizacao/finalizacao",
            "render": "renderizacao/finalizacao",
        }
        msg = (
            f"Continuar a partir de: {labels.get(resume_step, resume_step)}?\n\n"
            f"Frases prontas: {done}/{total}\n"
            f"Frases restantes: {max(0, total - done)}"
        )
        if not messagebox.askyesno("Continuar Dublagem", msg):
            return

        self.is_running = True
        self.btn_start.configure(state="disabled")
        self.btn_resume.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_bar_widget.set(0)
        self.progress_var.set(0.0)
        self.log_textbox.delete(1.0, "end")
        self._console_reset()
        self.stage_var.set("Continuando dublagem...")

        thread = threading.Thread(target=self.run_resume_pipeline, args=(resume_step,))
        thread.daemon = True
        thread.start()

    def run_resume_pipeline(self, resume_step="tts"):
        """Executa a etapa adequada para retomar."""
        try:
            self.log(f"Retomando pipeline a partir de: {resume_step}", "SUCCESS")
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["COQUI_TOS_ALLOW_PROMPT"] = "1"

            if resume_step == "translate":
                script = str(Path("scripts") / "traduzir_para_pt.py")
                self.stage_var.set("Etapa 2/5: Traduzindo e continuando...")
            elif resume_step in ("sync", "render"):
                script = str(Path("scripts") / "sincronizar_e_juntar.py")
                self.stage_var.set("Etapa 5/5: Sincronizando e Renderizando...")
            else:
                script = str(Path("scripts") / "dublar_frases_pt.py")
                self.stage_var.set("Etapa 4/5: Dublando com IA...")

            self.log(f"Executando retomada: {script}", "INFO")
            process = subprocess.Popen(
                [sys.executable, script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
            self._running_process = process

            for line in process.stdout:
                if not self.is_running:
                    process.terminate()
                    break
                line = line.strip()
                if line:
                    self.log(line)

            process.wait()
            self._running_process = None
            if not self.is_running:
                self.log("Processo interrompido pelo usuario.", "WARNING")
                return
            if process.returncode != 0:
                self.log(f"{script} encerrou com erro (codigo {process.returncode}).", "ERROR")
                return
            self.log("Retomada concluida!", "SUCCESS")
        except Exception as e:
            self.log(f"Erro critico ao retomar: {str(e)}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
        finally:
            self._running_process = None
            self.cleanup_ui()

    def run_batch_pipeline(self, queue_items):
        try:
            total = len(queue_items)
            self.log(f"Iniciando fila com {total} video(s).", "SUCCESS")
            env_base = os.environ.copy()
            env_base["PYTHONIOENCODING"] = "utf-8"
            env_base["COQUI_TOS_ALLOW_PROMPT"] = "1"

            for index, item in enumerate(queue_items, 1):
                if not self.is_running:
                    self.log("Fila interrompida pelo usuario.", "WARNING")
                    return

                mode = item["mode"]
                target = item["target"]
                self.stage_var.set(f"Fila {index}/{total}: iniciando...")
                self.progress_var.set(0.0)
                self.log("=" * 60, "INFO")
                self.log(f"Fila {index}/{total}: dublando {target}", "SUCCESS")

                input_str = f"1\n{target}\n" if mode == "url" else f"2\n{target}\n"
                process = subprocess.Popen(
                    [sys.executable, str(Path("scripts") / "transcrever.py")],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    env=env_base.copy(),
                    encoding="utf-8",
                    errors="replace",
                )
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
                self._running_process = None

                if not self.is_running:
                    self.log("Fila interrompida pelo usuario.", "WARNING")
                    return
                if process.returncode != 0:
                    self.log(f"Fila parada: item {index}/{total} falhou (codigo {process.returncode}).", "ERROR")
                    return

                self.log(f"Item {index}/{total} concluido.", "SUCCESS")

            self.log("Fila de dublagem concluida com sucesso!", "SUCCESS")
            self.root.after(0, lambda: messagebox.showinfo("Sucesso", "Todas as dublagens da fila foram concluidas."))
            self.execute_post_action()
        except Exception as e:
            self.log(f"Erro critico na fila: {str(e)}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
        finally:
            self._running_process = None
            self.cleanup_ui()

    def execute_post_action(self):
        action = self.post_action.get()
        if action == "Desligar":
            self.log("A fila terminou. O Windows sera desligado em 60 segundos.", "WARNING")
            subprocess.Popen(["shutdown", "/s", "/t", "60", "/c", "Dublagem concluida. Desligando em 60 segundos."])
        elif action == "Hibernar":
            self.log("A fila terminou. Colocando o Windows em hibernacao.", "WARNING")
            subprocess.Popen(["shutdown", "/h"])

    def run_pipeline(self, mode, target):
        try:
            self.log("🚀 Iniciando pipeline de dublagem completo...", "SUCCESS")
            
            input_str = f"1\n{target}\n" if mode == "url" else f"2\n{target}\n"
            
            self.log(f"Executando transcrever.py com alvo: {target}")
            
            cmd = [sys.executable, str(Path("scripts") / "transcrever.py")]
            
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            # Permite que o Coqui TTS mostre o prompt de termos via stdin pipe (GUI).
            # Sem isso, o XTTS pode ser bloqueado em modo não-TTY.
            env["COQUI_TOS_ALLOW_PROMPT"] = "1"

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
                self.execute_post_action()
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
        self.btn_resume.configure(state="normal")
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

