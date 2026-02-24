import os
import shutil

# Liste aqui os arquivos e pastas a serem removidos
itens_para_remover = [
    "audio.wav",
    "transcricao.json",
    "transcricao_pt.json",
    "frases_pt.json",
    "voz_dublada.wav",
    "audio_final_mix.wav",
    "audio_final_xtts.wav",
    "audio_final_xtts_musica.wav",
    "audios_frases_pt",
    "audios_frases_pt_stretched",
    "temp_segments",
    "temp_audio",
    "temp_stretched",
    "separated",
    "vocals.wav",
    "video_original.txt",
]

for item in itens_para_remover:
    if os.path.isfile(item):
        try:
            os.remove(item)
            print(f"Arquivo removido: {item}")
        except Exception as e:
            print(f"Erro ao remover arquivo {item}: {e}")
    elif os.path.isdir(item):
        try:
            shutil.rmtree(item)
            print(f"Pasta removida: {item}")
        except Exception as e:
            print(f"Erro ao remover pasta {item}: {e}")

print("✅ Limpeza concluída!")