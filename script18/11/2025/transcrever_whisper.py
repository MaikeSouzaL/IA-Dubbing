import os, json, glob
from pydub import AudioSegment
import webrtcvad
import subprocess
import whisper

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
    audio = audio.set_frame_rate(target_sample_rate).set_channels(1)
    samples = audio.raw_data
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
                chunks.append(fname)
            start = None
    if start is not None:
        end = len(audio) / 1000
        if end - start >= min_dur:
            chunk = audio[int(start*1000):int(end*1000)]
            fname = f"{base}_{len(chunks):03d}.wav"
            chunk.export(fname, format="wav")
            chunks.append(fname)
    return chunks

def transcrever_whisper(audio_paths, model_name="medium"):
    model = whisper.load_model(model_name)
    resultados = []
    for arquivo in audio_paths:
        print(f"🔊 Transcrevendo {arquivo} ...")
        result = model.transcribe(arquivo, language="hi", word_timestamps=True, verbose=False)
        palavras = []
        # Whisper retorna segmentos, cada um pode ter várias palavras
        for seg in result.get("segments", []):
            for w in seg.get("words", []):
                palavras.append({
                    "word": w["word"],
                    "start": w["start"],
                    "end": w["end"]
                })
        resultados.append({
            "chunk": arquivo,
            "transcript": result["text"],
            "words": palavras
        })
    return resultados

if __name__ == "__main__":
    f = input("Nome do arquivo (ex: UberClone.mp4): ").strip()
    if not os.path.isfile(f):
        print("❌ Arquivo não encontrado.")
        exit(1)

    base = os.path.splitext(os.path.basename(f))[0]
    vocals_path = os.path.join("separated", "htdemucs", base, "vocals.wav")
    arquivos_vad = sorted(glob.glob(f"{base}_*.wav"))
    if arquivos_vad:
        print(f"Encontrados {len(arquivos_vad)} arquivos segmentados pelo VAD. Pulando segmentação.")
        chunks = arquivos_vad
    else:
        if not os.path.isfile(vocals_path):
            vocals_path = separar_vocals_demucs(f)
        print("Segmentando áudio de voz isolada em frases com VAD...")
        chunks = dividir_audio_vad(vocals_path)

    data = transcrever_whisper(chunks, model_name="medium")

    out = "transcricao.json"
    with open(out, "w", encoding="utf-8") as j:
        json.dump(data, j, ensure_ascii=False, indent=2)
    print(f"✅ Transcrição salva em {out}")

    if not arquivos_vad:
        for c in chunks:
            os.remove(c)