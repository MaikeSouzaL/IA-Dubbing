import json

# Carrega o JSON
with open('frases_pt.json', 'r', encoding='utf-8') as f:
    frases = json.load(f)

# Corrige a frase 191 (índice 190) que está muito longa
if len(frases) > 190:
    print(f"Frase original (190): {frases[190]['frase_pt'][:100]}...")
    # Encurta a frase problemática
    frases[190]['frase_pt'] = "Acho que uma coisa que está meio quebrada no mercado quando se trata de integrar IA,"
    print(f"Frase corrigida: {frases[190]['frase_pt']}")

# Salva de volta
with open('frases_pt.json', 'w', encoding='utf-8') as f:
    json.dump(frases, f, ensure_ascii=False, indent=2)

print("✅ Arquivo frases_pt.json corrigido!")
