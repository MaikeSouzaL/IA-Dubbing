import json
import re
import time
import subprocess
import sys
import os
try:
    from deep_translator import GoogleTranslator
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "deep-translator"], check=True)
    from deep_translator import GoogleTranslator

def split_sentences(transcript):
    # Divide o texto em frases usando pontuação comum (inclui o ponto hindi '।')
    frases = re.split(r'(?<=[.!?।])\s+', transcript)
    return [f.strip() for f in frases if f.strip()]

def alinhar_frases_palavras(frases, words, max_duracao=10.0):
    frases_com_tempo = []
    idx = 0
    for frase in frases:
        frase_palavras = frase.split()
        if not frase_palavras:
            continue
        start = words[idx]["start"]
        end = words[min(idx + len(frase_palavras) - 1, len(words)-1)]["end"]
        frases_com_tempo.append({
            "frase": frase,
            "start": start,
            "end": end
        })
        idx += len(frase_palavras)
    return frases_com_tempo

# Carrega o JSON original
with open("transcricao.json", "r", encoding="utf-8") as f:
    data = json.load(f)

frases_pt = []
total = 0
for chunk in data:
    transcript = chunk.get("transcript", "")
    words = chunk.get("words", [])
    frases = split_sentences(transcript)
    frases_tempo = alinhar_frases_palavras(frases, words, max_duracao=10.0)
    total += len(frases_tempo)
    for frase_info in frases_tempo:
        frase_hi = frase_info["frase"]
        print(f"Traduzindo frase {len(frases_pt)+1}/{total}: {frase_hi[:60]}...")
        # Traduz cada frase individualmente com tentativas e pausa
        for tentativa in range(3):
            try:
                frase_pt = GoogleTranslator(source='auto', target='pt').translate(frase_hi)
                break
            except Exception as e:
                print(f"Erro ao traduzir, tentativa {tentativa+1}: {e}")
                time.sleep(2)
        else:
            frase_pt = ""
        # Troca ponto final por vírgula, se existir
        if frase_pt.endswith("."):
            frase_pt = frase_pt[:-1] + ","
        frases_pt.append({
            "frase_pt": frase_pt,
            "start": frase_info["start"],
            "end": frase_info["end"]
        })
        time.sleep(0.5)  # Pausa entre traduções

with open("frases_pt.json", "w", encoding="utf-8") as f:
    json.dump(frases_pt, f, ensure_ascii=False, indent=2)

print("✅ Frases em português com tempos salvas em frases_pt.json")

# Chama automaticamente o próximo passo
print("🔄 Iniciando dublagem das frases...")
subprocess.run([sys.executable, "dublar_frases_pt.py"], check=True, cwd=os.path.dirname(os.path.abspath(__file__)))