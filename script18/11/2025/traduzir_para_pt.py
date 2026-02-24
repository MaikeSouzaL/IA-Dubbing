import json
import subprocess
import sys
import os
try:
    from deep_translator import GoogleTranslator
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "deep-translator"], check=True)
    from deep_translator import GoogleTranslator

# Carrega o JSON com as transcrições
with open("transcricao.json", "r", encoding="utf-8") as f:
    data = json.load(f)

data_pt = []

total = len(data)
for idx, chunk in enumerate(data, 1):
    texto = chunk["transcript"]
    print(f"Traduzindo {idx}/{total} ...")
    try:
        traducao = GoogleTranslator(source='auto', target='pt').translate(texto)
    except Exception as e:
        print(f"Erro ao traduzir: {e}")
        traducao = ""
    novo_chunk = chunk.copy()
    novo_chunk["transcript_pt"] = traducao
    data_pt.append(novo_chunk)

# Salva o novo JSON com as traduções
with open("transcricao_pt.json", "w", encoding="utf-8") as f:
    json.dump(data_pt, f, ensure_ascii=False, indent=2)

print("✅ Tradução salva em transcricao_pt.json")

# Chama automaticamente o próximo passo
print("🔄 Iniciando extração de frases e tempos...")
subprocess.run([sys.executable, "extrair_frases_pt.py"], check=True, cwd=os.path.dirname(os.path.abspath(__file__)))