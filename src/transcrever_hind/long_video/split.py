import os
import tempfile
from pathlib import Path
from typing import List, Tuple
from .utils import ensure_dir, safe_run, ffprobe_duration

# Ajuste conforme sua preferência
MIN_PART_SEC = 12 * 60   # mínimo antes de permitir corte (~12 min)
MAX_PART_SEC = 20 * 60   # máximo tolerado; se não houver pausa, corta aqui (~20 min)
AUDIO_SR = 16000
FRAME_MS = 30
VAD_AGGR = 2
MIN_SILENCE_SEC = 0.6    # pausa mínima para aceitar como ponto de corte
FALLBACK_TOL_SEC = 120   # tolerância extra para achar pausa após o máximo

# raiz do projeto (pasta acima de long_video)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _extract_mono_wav(input_video: str, out_wav: str):
    safe_run([
        "ffmpeg", "-hide_banner", "-y",
        "-i", input_video,
        "-acodec", "pcm_s16le", "-ar", str(AUDIO_SR), "-ac", "1",
        out_wav
    ], check=True)

def _compute_silence_spans(wav_path: str) -> List[Tuple[float, float]]:
    import webrtcvad
    from pydub import AudioSegment
    audio = AudioSegment.from_file(wav_path)
    # alinhar para número inteiro de frames
    frame_size = max(1, audio.sample_width * audio.channels)
    frame_count = len(audio.raw_data) // frame_size
    audio = audio._spawn(audio.raw_data[:frame_count * frame_size])
    samples = audio.raw_data
    vad = webrtcvad.Vad(VAD_AGGR)
    frame_bytes = int(AUDIO_SR * 2 * FRAME_MS / 1000)  # 16-bit mono
    voiced = []
    for i in range(0, len(samples), frame_bytes):
        frame = samples[i:i+frame_bytes]
        if len(frame) < frame_bytes:
            break
        voiced.append(vad.is_speech(frame, sample_rate=AUDIO_SR))
    silences = []
    start = None
    for i, v in enumerate(voiced):
        if not v and start is None:
            start = i
        elif v and start is not None:
            end = i
            dur = (end - start) * FRAME_MS / 1000.0
            if dur >= MIN_SILENCE_SEC:
                s = start * FRAME_MS / 1000.0
                e = end * FRAME_MS / 1000.0
                silences.append((s, e))
            start = None
    if start is not None:
        end = len(voiced)
        dur = (end - start) * FRAME_MS / 1000.0
        if dur >= MIN_SILENCE_SEC:
            s = start * FRAME_MS / 1000.0
            e = end * FRAME_MS / 1000.0
            silences.append((s, e))
    return silences

def _compute_cuts_by_pauses(total_sec: float, silences: List[Tuple[float, float]],
                            min_part_sec=MIN_PART_SEC, max_part_sec=MAX_PART_SEC) -> List[float]:
    pause_times = sorted((s + e) / 2.0 for (s, e) in silences)
    cuts = []
    cur = 0.0
    idx = 0
    while True:
        if total_sec - cur <= min_part_sec:
            break
        min_t = cur + min_part_sec
        max_t = cur + max_part_sec
        while idx < len(pause_times) and pause_times[idx] < min_t:
            idx += 1
        chosen = None
        if idx < len(pause_times) and pause_times[idx] <= max_t:
            chosen = pause_times[idx]
        else:
            j = idx
            limit = max_t + FALLBACK_TOL_SEC
            while j < len(pause_times) and pause_times[j] <= limit:
                chosen = pause_times[j]
                break
            if chosen is None:
                chosen = max_t if max_t < total_sec else None
        if not chosen or chosen >= total_sec:
            break
        if cuts and (chosen - cuts[-1]) < 30.0:
            idx += 1
            continue
        cuts.append(chosen)
        cur = chosen
        while idx < len(pause_times) and pause_times[idx] <= chosen:
            idx += 1
    if cuts and (total_sec - cuts[-1]) < 10.0:
        cuts.pop()
    return cuts

def _ffmpeg_cut(input_video: str, cuts: List[float], out_dir: str) -> List[str]:
    out_dir = ensure_dir(out_dir)
    stem = Path(input_video).stem
    times = [0.0] + cuts + [ffprobe_duration(input_video) or 0.0]
    parts = []
    for i in range(len(times) - 1):
        ss = max(0.0, times[i])
        to = max(ss, times[i+1])
        out = os.path.join(out_dir, f"{stem}_part_{i:03d}.mp4")
        # tentar cópia (rápido)
        r = safe_run([
            "ffmpeg", "-hide_banner", "-y",
            "-ss", f"{ss:.3f}", "-to", f"{to:.3f}",
            "-i", input_video,
            "-c", "copy", "-map", "0", "-reset_timestamps", "1",
            out
        ], check=False)
        if r.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) == 0:
            # fallback: reencode para corte exato
            safe_run([
                "ffmpeg", "-hide_banner", "-y",
                "-ss", f"{ss:.3f}", "-to", f"{to:.3f}",
                "-i", input_video,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart",
                out
            ], check=True)
        parts.append(out)
    return parts

def split_video_into_parts(input_video: str, out_dir: str,
                           min_part_sec: int = MIN_PART_SEC,
                           max_part_sec: int = MAX_PART_SEC) -> list[str]:
    total_sec = ffprobe_duration(input_video) or 0.0
    if total_sec <= max_part_sec:
        out_dir = ensure_dir(out_dir)
        out = os.path.join(out_dir, f"{Path(input_video).stem}_part_000.mp4")
        safe_run(["ffmpeg", "-hide_banner", "-y", "-i", input_video, "-c", "copy", "-map", "0", out], check=True)
        return [out]
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "audio_mono_16k.wav")
        _extract_mono_wav(input_video, wav)
        silences = _compute_silence_spans(wav)
    cuts = _compute_cuts_by_pauses(total_sec, silences, min_part_sec, max_part_sec)
    output_dir = ROOT
    return _ffmpeg_cut(input_video, cuts, output_dir)