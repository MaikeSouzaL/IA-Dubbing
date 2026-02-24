import os, json, glob
from pydub import AudioSegment
import subprocess
import whisper
from deep_translator import GoogleTranslator
import sys

def separar_vocals_demucs(audio_path):
    base = os.path.splitext(os.path.basename(audio_path))[0]
    vocals_path = os.path.join("separated", "htdemucs", base, "vocals.wav")
    if not os.path.isfile(vocals_path):
        print("Separando voz com Demucs...")
        cmd = f'demucs "{audio_path}"'
        subprocess.run(cmd, shell=True)
    if not os.path.isfile(vocals_path):
        raise FileNotFoundError(f"vocals.wav não encontrado em {vocals_path}")
    return vocals_path

def dividir_audio_vad(audio_path, aggressiveness=2, target_sample_rate=16000, min_dur=0.5, max_dur=15.0):
    audio = AudioSegment.from_file(audio_path)
    audio = audio.set_frame_rate(target_sample_rate).set_channels(1).set_sample_width(2)
    samples = audio.raw_data
    import webrtcvad
    vad = webrtcvad.Vad(aggressiveness)
    frame_ms = 30
    frame_bytes = int(target_sample_rate * 2 * frame_ms / 1000)
    frames = [samples[i:i+frame_bytes] for i in range(0, len(samples), frame_bytes)]
    voiced = []
    for i, frame in enumerate(frames):
        if len(frame) < frame_bytes:
            break
        is_speech = vad.is_speech(frame, sample_rate=target_sample_rate)
        voiced.append(is_speech)
    # Agrupa frames em segmentos de fala
    chunks = []
    start = None
    base = os.path.splitext(os.path.basename(audio_path))[0]
    for i, speech_flag in enumerate(voiced):
        t = i * frame_ms / 1000
        if speech_flag and start is None:
            start = t
        elif not speech_flag and start is not None:
            end = t
            if end - start >= min_dur:
                if end - start > max_dur:
                    end = start + max_dur
                chunk = audio[int(start*1000):int(end*1000)]
                fname = f"{base}_{len(chunks):03d}.wav"
                chunk.export(fname, format="wav")
                chunks.append({"fname": fname, "start": start, "end": end})
            start = None
    # Caso termine falando
    if start is not None:
        end = len(audio) / 1000
        if end - start >= min_dur:
            chunk = audio[int(start*1000):int(end*1000)]
            fname = f"{base}_{len(chunks):03d}.wav"
            chunk.export(fname, format="wav")
            chunks.append({"fname": fname, "start": start, "end": end})
    return chunks

def detectar_idioma(audio_path):
    model = whisper.load_model("tiny")
    result = model.transcribe(audio_path, task="transcribe")
    return result["language"]

def transcrever_para_json(chunks):
    resultados = []
    model = whisper.load_model("medium")  # ou "small", "medium", "large" se quiser mais precisão
    idioma_whisper = detectar_idioma(chunks[0]["fname"])
    print(f"Idioma detectado: {idioma_whisper}")

    for chunk in chunks:
        arquivo = chunk["fname"]
        print(f"🔊 Processando {arquivo} ...")
        result = model.transcribe(arquivo, language=idioma_whisper, task="transcribe")
        transcript = result["text"].strip()
        palavras = []
        base_offset = float(chunk["start"])  # >>> soma o offset do chunk
        for seg in result.get("segments", []):
            for w in seg["text"].split():
                palavras.append({
                    "word": w,
                    "start": float(seg["start"]) + base_offset,
                    "end": float(seg["end"]) + base_offset
                })
        # Tradução automática para inglês
        try:
            transcript_en = GoogleTranslator(source='auto', target='en').translate(transcript)
        except Exception as e:
            print(f"Erro ao traduzir para inglês: {e}")
            transcript_en = ""
        resultados.append({
            "chunk": arquivo,
            "transcript": transcript,
            "transcript_en": transcript_en,
            "words": palavras,
            "start": chunk["start"],
            "end": chunk["end"]
        })
    return resultados

if __name__ == "__main__":
    print("Escolha uma opção:")
    print("1 - Inserir URL do vídeo do YouTube")
    print("2 - Inserir nome do arquivo local")
    escolha = input("Opção (1 ou 2): ").strip()

    if escolha == "1":
        url = input("Cole a URL do vídeo do YouTube: ").strip()
        # Baixa o vídeo usando yt-dlp
        print("⏬ Baixando vídeo do YouTube...")
        import yt_dlp
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': '%(title)s.%(ext)s',
            'merge_output_format': 'mp4'
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            f = ydl.prepare_filename(info)
        print(f"✅ Vídeo salvo como: {f}")
    elif escolha == "2":
        f = input("Nome do arquivo (ex: UberClone.mp4): ").strip()
    else:
        print("❌ Opção inválida.")
        exit(1)

    if not os.path.isfile(f):
        print("❌ Arquivo não encontrado.")
        exit(1)

    base = os.path.splitext(os.path.basename(f))[0]
    # Caminho do vocals.wav
    vocals_path = os.path.join("separated", "htdemucs", base, "vocals.wav")
    # Procura arquivos já segmentados
    arquivos_vad = sorted(glob.glob(f"{base}_*.wav"))
    if arquivos_vad:
        print(f"Encontrados {len(arquivos_vad)} arquivos segmentados pelo VAD. Pulando segmentação.")
        # Para manter compatibilidade, calcula tempos absolutos a partir dos arquivos
        chunks = []
        tempo_atual = 0.0
        for fname in arquivos_vad:
            audio = AudioSegment.from_file(fname)
            dur = len(audio) / 1000.0
            chunks.append({"fname": fname, "start": tempo_atual, "end": tempo_atual + dur})
            tempo_atual += dur
    else:
        # Se não existir vocals.wav, roda Demucs
        if not os.path.isfile(vocals_path):
            vocals_path = separar_vocals_demucs(f)
        print("Segmentando áudio de voz isolada em frases com VAD...")
        chunks = dividir_audio_vad(vocals_path)

    data = transcrever_para_json(chunks)

    # Salva todo o JSON
    out = "transcricao.json"
    with open(out, "w", encoding="utf-8") as j:
        json.dump(data, j, ensure_ascii=False, indent=2)
    print(f"✅ Transcrição salva em {out}")

    # Limpa sempre os arquivos segmentados
    for c in chunks:
        if os.path.exists(c["fname"]):
            os.remove(c["fname"])

    # Salva o nome do vídeo original para as próximas etapas
    with open("video_original.txt", "w", encoding="utf-8") as f_video:
        f_video.write(f)

    # Chama o script de tradução automaticamente
    print("🔄 Iniciando tradução automática para português...")
    ROOT = os.path.dirname(os.path.abspath(__file__))
    subprocess.run([sys.executable, "traduzir_para_pt.py"], check=True, cwd=ROOT)