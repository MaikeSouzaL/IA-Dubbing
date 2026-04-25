"""
Script para juntar múltiplos vídeos em um único arquivo.
Usa ffmpeg para concatenar os vídeos na ordem especificada.
"""
import os
import subprocess
import tempfile
from pathlib import Path

def merge_videos(video_paths, output_path, logger=None):
    """
    Junta múltiplos vídeos em um único arquivo.
    
    Args:
        video_paths: Lista de caminhos dos vídeos na ordem desejada
        output_path: Caminho do arquivo de saída
        logger: Função de log opcional (aceita mensagem e nível)
    
    Returns:
        bool: True se o merge foi bem-sucedido, False caso contrário
    """
    if not video_paths or len(video_paths) < 2:
        if logger:
            logger("❌ É necessário pelo menos 2 vídeos para juntar", "ERROR")
        return False
    
    # Valida que todos os arquivos existem
    for video_path in video_paths:
        if not os.path.isfile(video_path):
            if logger:
                logger(f"❌ Arquivo não encontrado: {video_path}", "ERROR")
            return False
    
    # Cria arquivo temporário com lista de vídeos para ffmpeg
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            concat_file = f.name
            for video_path in video_paths:
                # Escapa aspas e barras para o formato do ffmpeg
                abs_path = os.path.abspath(video_path).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
        
        if logger:
            logger(f"📝 Lista de concatenação criada com {len(video_paths)} vídeo(s)", "INFO")
        
        # Comando ffmpeg para concatenar
        cmd = [
            "ffmpeg",
            "-y",  # Sobrescreve arquivo de saída se existir
            "-hide_banner",  # Oculta banner do ffmpeg
            "-f", "concat",
            "-safe", "0",  # Permite caminhos absolutos
            "-i", concat_file,
            "-c", "copy",  # Copia streams sem re-encodar (mais rápido)
            output_path
        ]
        
        if logger:
            logger(f"🔗 Concatenando vídeos...", "INFO")
            for i, vp in enumerate(video_paths, 1):
                logger(f"   {i}. {os.path.basename(vp)}", "INFO")
        
        # Executa ffmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        # Remove arquivo temporário
        try:
            os.remove(concat_file)
        except:
            pass
        
        if result.returncode != 0:
            if logger:
                logger(f"❌ Erro ao juntar vídeos: {result.stderr[:500]}", "ERROR")
            return False
        
        # Verifica se o arquivo foi criado corretamente
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            if logger:
                logger(f"✅ Vídeos juntados com sucesso!", "SUCCESS")
                logger(f"📊 Arquivo final: {os.path.basename(output_path)} ({size_mb:.1f} MB)", "INFO")
            return True
        else:
            if logger:
                logger("❌ Arquivo de saída não foi criado ou está vazio", "ERROR")
            return False
            
    except Exception as e:
        if logger:
            logger(f"❌ Erro crítico ao juntar vídeos: {str(e)}", "ERROR")
        return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 4:
        print("Uso: python merge_videos.py <video1> <video2> ... <output>")
        print("Exemplo: python merge_videos.py video1.mp4 video2.mp4 video3.mp4 output.mp4")
        sys.exit(1)
    
    video_paths = sys.argv[1:-1]
    output_path = sys.argv[-1]
    
    def log(msg, level="INFO"):
        print(f"[{level}] {msg}")
    
    success = merge_videos(video_paths, output_path, logger=log)
    sys.exit(0 if success else 1)


