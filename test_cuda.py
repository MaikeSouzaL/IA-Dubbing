import torch
import sys

print("=" * 60)
print("🔍 TESTE DE CUDA + PYTORCH")
print("=" * 60)

# 1. Versão do PyTorch
print(f"\n📦 PyTorch Version: {torch.__version__}")

# 2. CUDA disponível?
cuda_available = torch.cuda.is_available()
print(f"🎮 CUDA Available: {cuda_available}")

if cuda_available:
    # 3. Versão CUDA que PyTorch está usando
    print(f"⚡ CUDA Version (PyTorch): {torch.version.cuda}")
    
    # 4. GPU detectada
    print(f"🖥️  GPU Device: {torch.cuda.get_device_name(0)}")
    
    # 5. Propriedades da GPU
    props = torch.cuda.get_device_properties(0)
    print(f"📊 Total Memory: {props.total_memory / 1024**3:.1f} GB")
    print(f"🔢 Compute Capability: {props.major}.{props.minor}")
    
    # 6. Teste de operação na GPU
    print("\n🧪 Testando operação na GPU...")
    try:
        x = torch.randn(1000, 1000).cuda()
        y = torch.randn(1000, 1000).cuda()
        z = torch.matmul(x, y)
        print("✅ Operação na GPU: SUCESSO!")
        
        # Limpar memória
        del x, y, z
        torch.cuda.empty_cache()
    except Exception as e:
        print(f"❌ Erro na GPU: {e}")
    
    # 7. Triton disponível?
    print("\n⚡ Verificando Triton...")
    try:
        import triton
        print(f"✅ Triton Version: {triton.__version__}")
        print("✅ Triton: DISPONÍVEL")
    except ImportError:
        print("⚠️  Triton: NÃO INSTALADO")
        print("   Para instalar: pip install triton")
        
    # 8. Whisper com CUDA
    print("\n🎤 Verificando Whisper...")
    try:
        import whisper
        print(f"✅ Whisper instalado: {whisper.__version__ if hasattr(whisper, '__version__') else 'OK'}")
        
        # Teste rápido
        print("   Carregando modelo tiny para teste...")
        model = whisper.load_model("tiny", device="cuda")
        print("✅ Whisper pode usar GPU!")
        
        # Limpar
        del model
        torch.cuda.empty_cache()
    except Exception as e:
        print(f"⚠️  Whisper: {e}")
        
else:
    print("\n❌ CUDA não está disponível!")
    print("\n🔍 Diagnóstico:")
    print("   1. CUDA Toolkit instalado?")
    print("      - Execute: nvcc --version")
    print("   2. Driver NVIDIA atualizado?")
    print("      - Execute: nvidia-smi")
    print("   3. PyTorch com CUDA instalado?")
    print("      - Execute: pip list | grep torch")
    
    print("\n💡 Para instalar PyTorch com CUDA:")
    print("   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121")

# 9. Resumo final
print("\n" + "=" * 60)
print("📋 RESUMO")
print("=" * 60)

if cuda_available:
    print("✅ Sistema pronto para usar GPU!")
    print(f"✅ GPU: {torch.cuda.get_device_name(0)}")
    print(f"✅ VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    print(f"✅ CUDA: {torch.version.cuda}")
    
    # Verificar se Triton está OK
    try:
        import triton
        print("✅ Triton: Instalado (otimizações ativas)")
    except:
        print("⚠️  Triton: Não instalado (performance reduzida)")
        print("   Instale com: pip install triton")
else:
    print("❌ GPU não disponível - verifique instalação")

print("=" * 60)
