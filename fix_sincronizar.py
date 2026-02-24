"""
Script para adicionar suporte a no_vocals.wav no sincronizar_e_juntar.py
"""
import os

# Restaura o arquivo original
os.system('cp "script18/11/2025/sincronizar_e_juntar.py" sincronizar_e_juntar.py')

# Lê o arquivo
with open('sincronizar_e_juntar.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Código antigo da função
old_function = '''def carregar_fundo(bg_dir):
    stems = []
    for name in ["other.wav", "drums.wav", "bass.wav"]:
        path = os.path.join(bg_dir, name)
        if os.path.isfile(path):
            try:
                stems.append(AudioSegment.from_wav(path))
            except Exception as e:
                print(f"⚠️ Erro ao carregar {name}: {e}")
    if not stems:
        return None
    bg_mix = stems[0]
    for s in stems[1:]:
        bg_mix = bg_mix.overlay(s)
    return bg_mix'''

# Novo código com fallback para no_vocals.wav
new_function = '''def carregar_fundo(bg_dir):
    # Tenta carregar stems separados (modelo 4-stems)
    stems = []
    for name in ["other.wav", "drums.wav", "bass.wav"]:
        path = os.path.join(bg_dir, name)
        if os.path.isfile(path):
            try:
                stems.append(AudioSegment.from_wav(path))
            except Exception as e:
                print(f"⚠️ Erro ao carregar {name}: {e}")
    
    if stems:
        bg_mix = stems[0]
        for s in stems[1:]:
            bg_mix = bg_mix.overlay(s)
        print("✅ Usando stems separados (bass + drums + other)")
        return bg_mix
    
    # Fallback: usa no_vocals.wav (modelo 2-stems)
    no_vocals = os.path.join(bg_dir, "no_vocals.wav")
    if os.path.isfile(no_vocals):
        try:
            bg_mix = AudioSegment.from_wav(no_vocals)
            print("✅ Usando no_vocals.wav como música de fundo")
            return bg_mix
        except Exception as e:
            print(f"⚠️ Erro ao carregar no_vocals.wav: {e}")
    
    return None'''

# Substitui
content_new = content.replace(old_function, new_function)

# Escreve de volta
with open('sincronizar_e_juntar.py', 'w', encoding='utf-8') as f:
    f.write(content_new)

print("✅ Arquivo sincronizar_e_juntar.py atualizado com sucesso!")
print("✅ Agora suporta no_vocals.wav (modelo 2-stems)")
