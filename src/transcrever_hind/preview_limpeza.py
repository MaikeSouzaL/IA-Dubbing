"""
Script para visualizar o que será removido na limpeza COMPLETA
Execute antes de limpar para ver o que será deletado
"""
import os
import glob
from pathlib import Path

def formatar_tamanho(bytes):
    """Formata bytes em formato legível"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} TB"

def listar_arquivos_para_remover():
    """Lista todos os arquivos que serão removidos"""
    
    print("=" * 70)
    print("🗑️  PREVIEW DA LIMPEZA COMPLETA")
    print("=" * 70)
    print()
    
    total_size = 0
    items_to_remove = []
    
    # 1. Vídeo original
    print("📹 VÍDEO ORIGINAL:")
    print("-" * 70)
    if os.path.exists("video_original.txt"):
        try:
            with open("video_original.txt", "r", encoding="utf-8") as f:
                video_path = f.read().strip()
            if os.path.exists(video_path):
                size = os.path.getsize(video_path)
                total_size += size
                items_to_remove.append(("Vídeo Original", video_path, size))
                print(f"   ✗ {video_path} ({formatar_tamanho(size)})")
            else:
                print("   ℹ️  Vídeo original não encontrado")
        except:
            print("   ℹ️  Arquivo video_original.txt não encontrado")
    else:
        print("   ℹ️  Nenhum vídeo original registrado")
    print()
    
    # 2. Pasta separated/ (Demucs)
    print("🎵 STEMS DE ÁUDIO (Demucs):")
    print("-" * 70)
    if os.path.exists("separated"):
        for root, dirs, files in os.walk("separated"):
            for file in files:
                filepath = os.path.join(root, file)
                size = os.path.getsize(filepath)
                total_size += size
                items_to_remove.append(("Stem", filepath, size))
                print(f"   ✗ {filepath} ({formatar_tamanho(size)})")
    else:
        print("   ℹ️  Pasta 'separated/' não encontrada")
    print()
    
    # 3. JSONs
    print("📄 ARQUIVOS JSON:")
    print("-" * 70)
    json_files = ["transcricao.json", "transcricao_pt.json", "frases_pt.json"]
    for f in json_files:
        if os.path.exists(f):
            size = os.path.getsize(f)
            total_size += size
            items_to_remove.append(("JSON", f, size))
            print(f"   ✗ {f} ({formatar_tamanho(size)})")
        else:
            print(f"   ℹ️  {f} (não existe)")
    print()
    
    # 4. WAVs intermediários
    print("🎙️  ÁUDIOS INTERMEDIÁRIOS:")
    print("-" * 70)
    wav_files = ["voz_dublada.wav", "audio_final_mix.wav"]
    for f in wav_files:
        if os.path.exists(f):
            size = os.path.getsize(f)
            total_size += size
            items_to_remove.append(("WAV", f, size))
            print(f"   ✗ {f} ({formatar_tamanho(size)})")
        else:
            print(f"   ℹ️  {f} (não existe)")
    print()
    
    # 5. Chunks de voz (vocals_*.wav)
    print("🔊 CHUNKS DE VOZ:")
    print("-" * 70)
    vocals = glob.glob("vocals_*.wav")
    if vocals:
        chunk_size = sum(os.path.getsize(f) for f in vocals)
        total_size += chunk_size
        print(f"   ✗ {len(vocals)} arquivos vocals_*.wav ({formatar_tamanho(chunk_size)})")
        for v in vocals[:5]:  # Mostra só os primeiros 5
            print(f"      • {v}")
        if len(vocals) > 5:
            print(f"      • ... e mais {len(vocals) - 5} arquivos")
    else:
        print("   ℹ️  Nenhum chunk de voz encontrado")
    print()
    
    # 6. Diretórios
    print("📁 DIRETÓRIOS:")
    print("-" * 70)
    dirs = ["audios_frases_pt", "audios_frases_pt_stretched", "cache", "temp"]
    for d in dirs:
        if os.path.exists(d):
            dir_size = sum(
                os.path.getsize(os.path.join(root, f))
                for root, _, files in os.walk(d)
                for f in files
            )
            total_size += dir_size
            num_files = sum(len(files) for _, _, files in os.walk(d))
            items_to_remove.append(("Diretório", d, dir_size))
            print(f"   ✗ {d}/ ({num_files} arquivos, {formatar_tamanho(dir_size)})")
        else:
            print(f"   ℹ️  {d}/ (não existe)")
    print()
    
    # 7. Vídeos dublados (MANTIDOS)
    print("✅ VÍDEOS DUBLADOS (SERÃO MANTIDOS):")
    print("-" * 70)
    videos_dublados = glob.glob("*_dublado.mp4")
    if videos_dublados:
        for video in videos_dublados:
            size = os.path.getsize(video)
            print(f"   ✓ {video} ({formatar_tamanho(size)}) ← MANTIDO!")
    else:
        print("   ⚠️  NENHUM VÍDEO DUBLADO ENCONTRADO!")
        print("   ⚠️  Execute o processo de dublagem primeiro!")
    print()
    
    # Resumo
    print("=" * 70)
    print("📊 RESUMO:")
    print("=" * 70)
    print(f"   Total de itens a remover: {len(items_to_remove)}")
    print(f"   Espaço a ser liberado:    {formatar_tamanho(total_size)}")
    print(f"   Vídeos dublados mantidos: {len(videos_dublados)}")
    print("=" * 70)
    print()
    
    if videos_dublados:
        print("✅ Tudo pronto para limpar!")
        print("   Execute: python limpar_projeto.py")
    else:
        print("⚠️  ATENÇÃO: Nenhum vídeo dublado encontrado!")
        print("   Não execute a limpeza até ter o vídeo dublado.")
    print()

if __name__ == "__main__":
    listar_arquivos_para_remover()
