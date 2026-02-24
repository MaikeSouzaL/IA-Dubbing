"""
🧪 Teste de Performance - Whisper com Triton
Compara tempo de processamento antes/depois
"""
import time
import whisper
import torch
from pydub import AudioSegment
import os

print("=" * 60)
print("🧪 TESTE DE PERFORMANCE - WHISPER + TRITON")
print("=" * 60)

# Verificar Triton
try:
    import triton
    print(f"\n✅ Triton {triton.__version__} detectado")
except:
    print("\n❌ Triton não encontrado")

# Criar áudio de teste (se não existir)
test_audio = "test_audio_sample.wav"
if not os.path.exists(test_audio):
    print("\n📝 Criando áudio de teste (5s)...")
    # Usar um dos chunks existentes se disponível
    vocals_dir = "vocals_000.wav"
    if os.path.exists(vocals_dir):
        test_audio = vocals_dir
    else:
        print("⚠️  Nenhum áudio de teste encontrado")
        print("   Execute uma dublagem primeiro ou coloque um arquivo WAV aqui")
        exit(1)

print(f"\n🎵 Usando arquivo: {test_audio}")

# Teste 1: Modelo Tiny (rápido)
print("\n" + "-" * 60)
print("📊 Teste 1: Whisper Tiny")
print("-" * 60)

model = whisper.load_model("tiny", device="cuda")
print(f"✅ Modelo carregado na GPU")

# Warm-up (primeira execução é sempre mais lenta)
print("🔥 Warm-up...")
_ = model.transcribe(test_audio, language="en", verbose=False)

# Teste real (3 execuções para média)
print("⏱️  Executando 3 testes...")
times = []
for i in range(3):
    start = time.time()
    result = model.transcribe(
        test_audio, 
        language="en",
        word_timestamps=True,
        verbose=False
    )
    elapsed = time.time() - start
    times.append(elapsed)
    print(f"   Teste {i+1}: {elapsed:.2f}s")

avg_time = sum(times) / len(times)
print(f"\n✅ Tempo médio: {avg_time:.2f}s")
print(f"📝 Texto: {result['text'][:50]}...")

# Estatísticas de GPU
if torch.cuda.is_available():
    vram_used = torch.cuda.max_memory_allocated() / 1024**2
    print(f"📊 VRAM usada (pico): {vram_used:.1f} MB")
    torch.cuda.reset_peak_memory_stats()

# Limpar
del model
torch.cuda.empty_cache()

print("\n" + "=" * 60)
print("✅ TESTE CONCLUÍDO")
print("=" * 60)
print("\n💡 Dicas:")
print("   - Tempo < 1s/chunk = Excelente")
print("   - Tempo 1-2s/chunk = Bom")
print("   - Tempo > 2s/chunk = Pode melhorar")
print("\n🎯 Próximo passo: Testar com vídeo real!")
