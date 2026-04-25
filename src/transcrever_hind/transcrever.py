import os
import sys
import subprocess
import glob
from pydub import AudioSegment
import whisper
from deep_translator import GoogleTranslator

# Local imports
from config_loader import config
from logger import setup_logger, log_progress
from utils import save_json, safe_remove
from transcription_providers import (
    get_provider_model,
    get_provider_name,
    result_to_pipeline_chunk,
    transcribe_external,
)
from job_manager import add_artifact, copy_artifact, create_job, mark_step
from project_paths import (
    ROOT,
    cache_file,
    ensure_project_dirs,
    input_file,
    output_file,
    report_file,
    temp_dir,
    temp_file,
    video_original_file,
    work_file,
)

logger = setup_logger(__name__)

LOCAL_TRANSCRIPTION_PROVIDERS = {"local_whisper", "local_faster_whisper"}

def separar_vocals_demucs(audio_path):
    """Separa vocais usando Demucs com suporte a GPU."""
    base = os.path.splitext(os.path.basename(audio_path))[0]
    sep_dir = config.get("paths.separated_dir", "separated")
    model_name = config.get("models.demucs.model", "htdemucs")
    vocals_path = os.path.join(sep_dir, model_name, base, "vocals.wav")
    
    if not os.path.isfile(vocals_path):
        logger.info("Separando voz com Demucs...")
        
        # Detecta se GPU está disponível
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        try:
            # Executa demucs COM SUPORTE A GPU! 🚀
            cmd = ["demucs", "-n", model_name, "-d", device, "--two-stems=vocals", audio_path]
            
            if device == "cuda":
                logger.info("🎮 Usando GPU para separação de vozes (Demucs)")
            else:
                logger.info("🖥️ Usando CPU para separação de vozes (Demucs)")
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if result.returncode != 0:
                logger.error(f"Erro Demucs: {result.stderr.strip()[:500]}")
        except FileNotFoundError:
            logger.error("demucs não encontrado. Instale com: pip install demucs")
            
    if not os.path.isfile(vocals_path):
        logger.warning(f"vocals.wav não encontrado em {vocals_path}, verificando estrutura...")
        found = glob.glob(f"**/{base}/vocals.wav", recursive=True)
        if found:
            vocals_path = found[0]
            logger.info(f"Encontrado em: {vocals_path}")
        else:
            raise FileNotFoundError(f"vocals.wav não encontrado após execução do Demucs.")
        
    return vocals_path

def dividir_audio_vad(audio_path):
    """Segmenta o áudio usando webrtcvad."""
    aggressiveness = config.get("audio.vad.aggressiveness", 2)
    target_sample_rate = config.get("audio.vad.sample_rate", 16000)
    min_dur = config.get("audio.vad.min_duration", 0.5)
    max_dur = config.get("audio.vad.max_duration", 15.0)
    frame_ms = config.get("audio.vad.frame_ms", 30)
    
    logger.info(f"Iniciando VAD (aggressiveness={aggressiveness}, min={min_dur}s, max={max_dur}s)")
    audio = AudioSegment.from_file(audio_path)
    audio = audio.set_frame_rate(target_sample_rate).set_channels(1).set_sample_width(2)
    samples = audio.raw_data

    import webrtcvad
    vad = webrtcvad.Vad(aggressiveness)
    frame_bytes = int(target_sample_rate * 2 * frame_ms / 1000)
    frames = [samples[i:i+frame_bytes] for i in range(0, len(samples), frame_bytes)]
    voiced = []
    for i, frame in enumerate(frames):
        if len(frame) < frame_bytes:
            break
        voiced.append(vad.is_speech(frame, sample_rate=target_sample_rate))

    chunks = []
    start = None
    base = os.path.splitext(os.path.basename(audio_path))[0]
    temp_dir().mkdir(parents=True, exist_ok=True)

    def save_chunk(s, e):
        chunk_audio = audio[int(s*1000):int(e*1000)]
        fname = str(temp_file(f"{base}_{len(chunks):03d}.wav"))
        chunk_audio.export(fname, format="wav")
        chunks.append({"fname": fname, "start": s, "end": e, "temp": True})

    for i, speech in enumerate(voiced):
        t = i * frame_ms / 1000.0
        if speech and start is None:
            start = t
        elif not speech and start is not None:
            end = t
            if end - start >= min_dur:
                if end - start > max_dur:
                    end = start + max_dur
                save_chunk(start, end)
            start = None
    if start is not None:
        end = len(audio) / 1000.0
        if end - start >= min_dur:
            save_chunk(start, end)
    return chunks

def detectar_idioma(audio_path):
    """Detecta idioma do áudio usando Whisper tiny."""
    logger.info("Detectando idioma...")
    tiny_model = whisper.load_model("tiny")
    result = tiny_model.transcribe(audio_path, task="transcribe")
    lang = result.get("language", "en")
    logger.info(f"Idioma detectado: {lang}")
    return lang

def transcrever_para_json(chunks, idioma, model, traduzir_en=False):
    """Transcreve chunks de áudio para JSON com timestamps."""
    if not chunks:
        raise RuntimeError("Nenhum chunk gerado para transcrição.")
    resultados = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        percent = (i / total) * 20.0
        log_progress(logger, percent)
        arquivo = chunk["fname"]
        logger.info(f"🔊 Processando chunk {i+1}/{total}: {arquivo}")
        try:
            result = model.transcribe(
                arquivo,
                language=idioma,
                task="transcribe",
                word_timestamps=True,
                fp16=bool(getattr(model, "_use_fp16", False)),
            )
        except Exception as e:
            logger.warning(f"Falha transcrição detalhada, tentando sem word_timestamps: {e}")
            result = model.transcribe(
                arquivo,
                language=idioma,
                task="transcribe",
                fp16=bool(getattr(model, "_use_fp16", False)),
            )
        transcript = (result.get("text") or "").strip()
        palavras = []
        base_offset = float(chunk["start"])
        for seg in result.get("segments", []):
            seg_start = float(seg.get("start", 0.0)) + base_offset
            seg_end = float(seg.get("end", seg_start)) + base_offset
            if "words" in seg:
                for w in seg["words"]:
                    w_start = float(w.get("start", seg_start)) + base_offset
                    w_end = float(w.get("end", seg_end)) + base_offset
                    txt = (w.get("word") or "").strip()
                    if txt:
                        palavras.append({"word": txt, "start": w_start, "end": w_end})
            else:
                for w_txt in seg.get("text", "").split():
                    palavras.append({"word": w_txt, "start": seg_start, "end": seg_end})
        transcript_en = ""
        if traduzir_en and transcript:
            try:
                transcript_en = GoogleTranslator(source='auto', target='en').translate(transcript)
            except Exception as e:
                logger.warning(f"Erro tradução EN: {e}")
        resultados.append({
            "chunk": arquivo,
            "transcript": transcript,
            "transcript_en": transcript_en,
            "words": palavras,
            "start": chunk["start"],
            "end": chunk["end"],
        })
    log_progress(logger, 20.0)
    return resultados

def transcrever_para_json_faster_whisper(chunks, idioma, model, traduzir_en=False):
    """Transcreve chunks usando Faster-Whisper e converte para o formato interno."""
    if not chunks:
        raise RuntimeError("Nenhum chunk gerado para transcricao.")
    resultados = []
    total = len(chunks)
    beam_size = int(config.get("models.faster_whisper.beam_size", 5))
    vad_filter = bool(config.get("models.faster_whisper.vad_filter", False))
    for i, chunk in enumerate(chunks):
        percent = (i / total) * 20.0
        log_progress(logger, percent)
        arquivo = chunk["fname"]
        logger.info(f"Processando chunk {i+1}/{total} com Faster-Whisper: {arquivo}")
        kwargs = {
            "task": "transcribe",
            "beam_size": beam_size,
            "word_timestamps": True,
            "vad_filter": vad_filter,
        }
        if idioma:
            kwargs["language"] = idioma
        segments, info = model.transcribe(arquivo, **kwargs)
        transcript_parts = []
        palavras = []
        base_offset = float(chunk["start"])
        for segment in segments:
            segment_text = (getattr(segment, "text", "") or "").strip()
            if segment_text:
                transcript_parts.append(segment_text)
            words = getattr(segment, "words", None) or []
            if words:
                for word in words:
                    txt = (getattr(word, "word", "") or "").strip()
                    if not txt:
                        continue
                    palavras.append({
                        "word": txt,
                        "start": float(getattr(word, "start", 0.0) or 0.0) + base_offset,
                        "end": float(getattr(word, "end", 0.0) or 0.0) + base_offset,
                    })
            elif segment_text:
                seg_start = float(getattr(segment, "start", 0.0) or 0.0) + base_offset
                seg_end = float(getattr(segment, "end", 0.0) or 0.0) + base_offset
                for w_txt in segment_text.split():
                    palavras.append({"word": w_txt, "start": seg_start, "end": seg_end})
        transcript = " ".join(transcript_parts).strip()
        transcript_en = ""
        if traduzir_en and transcript:
            try:
                transcript_en = GoogleTranslator(source='auto', target='en').translate(transcript)
            except Exception as e:
                logger.warning(f"Erro traducao EN: {e}")
        resultados.append({
            "chunk": arquivo,
            "transcript": transcript,
            "transcript_en": transcript_en,
            "words": palavras,
            "start": chunk["start"],
            "end": chunk["end"],
            "provider": "local_faster_whisper",
            "model": getattr(info, "model_name", config.get("models.faster_whisper.size", "large-v3-turbo")),
            "language": getattr(info, "language", idioma or ""),
        })
    log_progress(logger, 20.0)
    return resultados

def transcrever_externo_para_json(audio_path, idioma=None, start=0.0, end=None):
    """Transcreve via API externa e converte para o formato interno do pipeline."""
    if config.get("app.offline_mode", False):
        raise RuntimeError("Modo offline ativo: provedores externos de transcricao estao desabilitados.")
    provider = get_provider_name()
    result = transcribe_external(audio_path, provider, language=idioma)
    if end is None:
        audio = AudioSegment.from_file(audio_path)
        end = len(audio) / 1000.0
    chunk = result_to_pipeline_chunk(result, audio_path, float(start), float(end))
    log_progress(logger, 20.0)
    return [chunk]

def salvar_manifesto_chunks(chunks, path=None):
    try:
        path = path or cache_file("chunks_manifest.json")
        save_json(chunks, path)
    except Exception as e:
        logger.debug(f"Falha ao salvar manifesto de chunks: {e}")

def encontrar_corte_silencioso(audio, target_ms, min_ms, max_ms, silence_thresh=-42, min_silence_ms=600):
    """Procura uma pausa perto do limite desejado para evitar cortar fala."""
    min_ms = max(0, int(min_ms))
    max_ms = min(len(audio), int(max_ms))
    target_ms = min(max(int(target_ms), min_ms), max_ms)
    if max_ms <= min_ms:
        return target_ms

    step_ms = 100
    best_cut = None
    best_distance = None
    silence_start = None

    for pos in range(min_ms, max_ms, step_ms):
        window = audio[pos:min(pos + step_ms, max_ms)]
        is_silent = window.dBFS == float("-inf") or window.dBFS <= silence_thresh
        if is_silent and silence_start is None:
            silence_start = pos
        elif (not is_silent) and silence_start is not None:
            if pos - silence_start >= min_silence_ms:
                candidate = silence_start + ((pos - silence_start) // 2)
                distance = abs(candidate - target_ms)
                if best_distance is None or distance < best_distance:
                    best_cut = candidate
                    best_distance = distance
            silence_start = None

    if silence_start is not None and max_ms - silence_start >= min_silence_ms:
        candidate = silence_start + ((max_ms - silence_start) // 2)
        distance = abs(candidate - target_ms)
        if best_distance is None or distance < best_distance:
            best_cut = candidate

    return int(best_cut if best_cut is not None else target_ms)

def dividir_audio_api(audio_path, max_seconds=480):
    """Divide um audio longo em blocos seguros, preferindo cortes em silencio."""
    audio = AudioSegment.from_file(audio_path)
    total_ms = len(audio)
    max_ms = max(1, int(float(max_seconds) * 1000))
    overlap_ms = int(float(config.get("transcription.api_chunk_overlap_seconds", 2.0)) * 1000)
    search_ms = int(float(config.get("transcription.api_chunk_silence_search_seconds", 25.0)) * 1000)
    silence_thresh = float(config.get("transcription.api_chunk_silence_threshold_db", -42))
    min_silence_ms = int(config.get("transcription.api_chunk_min_silence_ms", 600))
    base = os.path.splitext(os.path.basename(audio_path))[0]
    api_chunks = []

    idx = 0
    start_ms = 0
    while start_ms < total_ms:
        target_end = min(start_ms + max_ms, total_ms)
        if target_end >= total_ms:
            end_ms = total_ms
        else:
            end_ms = encontrar_corte_silencioso(
                audio,
                target_ms=target_end,
                min_ms=max(start_ms + int(max_ms * 0.65), target_end - search_ms),
                max_ms=min(total_ms, target_end + search_ms),
                silence_thresh=silence_thresh,
                min_silence_ms=min_silence_ms,
            )
            if end_ms <= start_ms + 1000:
                end_ms = target_end

        export_start_ms = max(0, start_ms - (overlap_ms if idx > 0 else 0))
        chunk_path = str(temp_file(f"{base}_api_{idx:03d}.wav"))
        audio[export_start_ms:end_ms].export(chunk_path, format="wav")
        api_chunks.append({
            "fname": chunk_path,
            "start": export_start_ms / 1000.0,
            "end": end_ms / 1000.0,
            "temp": True,
            "api_chunk": True,
            "nominal_start": start_ms / 1000.0,
            "overlap_seconds": (start_ms - export_start_ms) / 1000.0,
        })
        idx += 1
        if end_ms >= total_ms:
            break
        start_ms = end_ms
    return api_chunks

def deduplicar_palavras_transcricao(data, tolerance=0.35):
    """Remove palavras duplicadas criadas por sobreposicao entre blocos."""
    seen = []
    cleaned = []
    for chunk in sorted(data, key=lambda x: float(x.get("start", 0.0))):
        new_words = []
        for word in chunk.get("words", []) or []:
            txt = (word.get("word") or "").strip().lower()
            start = float(word.get("start", 0.0))
            duplicate = False
            for prev_txt, prev_start in seen[-80:]:
                if txt == prev_txt and abs(start - prev_start) <= tolerance:
                    duplicate = True
                    break
            if not duplicate:
                new_words.append(word)
                seen.append((txt, start))
        new_chunk = chunk.copy()
        new_chunk["words"] = new_words
        if new_words:
            new_chunk["transcript"] = " ".join(w["word"] for w in new_words)
        cleaned.append(new_chunk)
    return cleaned

def gerar_relatorio_transcricao(data, output_path=None):
    output_path = output_path or report_file("transcription_report.json")
    try:
        total_words = 0
        confidences = []
        covered = 0.0
        gaps = []
        last_end = 0.0
        for chunk in sorted(data, key=lambda x: float(x.get("start", 0.0))):
            words = chunk.get("words", []) or []
            total_words += len(words)
            for w in words:
                if w.get("confidence") is not None:
                    try:
                        confidences.append(float(w["confidence"]))
                    except Exception:
                        pass
            start = float(chunk.get("start", 0.0))
            end = float(chunk.get("end", start))
            if start - last_end > 0.5:
                gaps.append({"start": last_end, "end": start, "duration": start - last_end})
            covered += max(0.0, end - start)
            last_end = max(last_end, end)
        report = {
            "chunks": len(data),
            "words": total_words,
            "covered_seconds": covered,
            "duration_until_last_chunk": last_end,
            "coverage_ratio": (covered / last_end) if last_end else 0.0,
            "gaps_over_500ms": gaps,
            "average_confidence": (sum(confidences) / len(confidences)) if confidences else None,
        }
        save_json(report, output_path)
        logger.info(f"Relatorio de qualidade salvo em {output_path}")
    except Exception as e:
        logger.warning(f"Nao foi possivel gerar relatorio de transcricao: {e}")

if __name__ == "__main__":
    ensure_project_dirs()
    # Flag para evitar divisão recursiva quando processando partes
    is_part = os.environ.get("TRANSCRIBER_IS_PART", "0") == "1"
    
    print("Escolha uma opção:")
    print("1 - Inserir URL do vídeo do YouTube")
    print("2 - Inserir nome do arquivo local")
    try:
        escolha = sys.stdin.readline().strip()
    except:
        escolha = input("Opção (1 ou 2): ").strip()
    f = ""
    if escolha == "1":
        if config.get("app.offline_mode", False):
            logger.error("Modo offline ativo: URLs do YouTube nao podem ser baixadas sem internet. Use um arquivo local.")
            sys.exit(1)
        try:
            url = sys.stdin.readline().strip()
        except:
            url = input("Cole a URL do vídeo do YouTube: ").strip()
        logger.info("⏬ Baixando vídeo do YouTube...")
        create_job(url, input_mode="url")
        mark_step("download", "running")
        try:
            import yt_dlp
        except ImportError:
            logger.info("Instalando yt-dlp...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], check=False, encoding='utf-8', errors='replace')
            import yt_dlp
            
        def yt_dlp_monitor(d):
            if d['status'] == 'downloading':
                try:
                    percent_str = d.get('_percent_str', '0.0%').replace('%', '').strip()
                    # Remove ANSI colors
                    import re
                    percent_str = re.sub(r'\x1b\[[0-9;]*m', '', percent_str)
                    percent = float(percent_str)
                    # Envia para a interface pegar via log
                    print(f"DOWNLOAD_PROGRESS: {percent}") 
                except:
                    pass

        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': str(input_file('%(title)s.%(ext)s')),
            'merge_output_format': 'mp4',
            'progress_hooks': [yt_dlp_monitor],
            'noprogress': True # Esconde a barrinha poluidora do terminal do yt-dlp
        }
        
        # Define uma lista de navegadores para tentar extrair os cookies caso o YouTube bloqueie por "Bot"
        browsers_to_try = [None, ('chrome',), ('edge',), ('firefox',), ('brave',), ('opera',)]
        
        f = None
        last_error = None
        for browser_tuple in browsers_to_try:
            opts = dict(ydl_opts)
            if browser_tuple:
                opts['cookiesfrombrowser'] = browser_tuple
                logger.info(f"🔄 Tentando bypass de Bot usando cookies do navegador: {browser_tuple[0]}...")
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    f = ydl.prepare_filename(info)
                logger.info(f"✅ Vídeo salvo como: {f}")
                mark_step("download", "done", path=os.path.abspath(f))
                add_artifact("input_video", f)
                break  # Sucesso! Sai do loop
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if "sign in to confirm" in err_str or "bot" in err_str or "cookie" in err_str or "dpapi" in err_str:
                    if browser_tuple is None:
                        logger.warning("⚠️ YouTube bloqueou o acesso pedindo login ou provar que não é um robô.")
                    # Continua para o próximo navegador no loop
                    continue
                elif "403" in err_str or "forbidden" in err_str:
                    logger.warning("⚠️ Erro 403 Forbidden retornado pelo YouTube. O yt-dlp pode estar desatualizado.")
                    logger.info("🔄 Tentando atualizar o yt-dlp automaticamente...")
                    subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], check=False)
                    import importlib
                    importlib.reload(yt_dlp)
                    # Tenta baixar novamente apenas uma vez com yt-dlp atualizado para 403
                    with yt_dlp.YoutubeDL(opts) as ydl_updated:
                        info = ydl_updated.extract_info(url, download=True)
                        f = ydl_updated.prepare_filename(info)
                    logger.info(f"✅ Vídeo salvo como: {f}")
                    break
                else:
                    raise e
        
        if not f:
            logger.error("❌ Não foi possível baixar o vídeo mesmo tentando usar cookies dos navegadores.")
            if last_error is not None:
                raise last_error
            else:
                raise Exception("Falha desconhecida sem erros prévios registrados.")
    elif escolha == "2":
        try:
            f = sys.stdin.readline().strip()
        except:
            f = input("Nome do arquivo (ex: Video.mp4): ").strip()
        create_job(f, input_mode="file")
        add_artifact("input_video", f)
    else:
        logger.error("Opção inválida.")
        sys.exit(1)
    if not os.path.isfile(f):
        logger.error(f"Arquivo não encontrado: {f}")
        sys.exit(1)
        
    if os.environ.get("TRANSCRIBER_PREVIEW") == "1":
        logger.info("🧪 MODO AMOSTRA ATIVADO: Recortando os primeiros 15 segundos do vídeo...")
        preview_f = str(temp_file(f"{os.path.splitext(os.path.basename(f))[0]}_preview{os.path.splitext(f)[1]}"))
        # Corta os primeiros 15s sem reencodar (rápido!)
        cmd_preview = ["ffmpeg", "-y", "-i", f, "-t", "15", "-c", "copy", preview_f]
        subprocess.run(cmd_preview, capture_output=True)
        f = preview_f
        logger.info(f"✅ Amostra extraída com sucesso!")
    
    # Verifica se o vídeo é muito grande e precisa ser dividido automaticamente
    # MAS apenas se não for uma parte de um vídeo maior (evita divisão recursiva)
    max_duration_minutes = config.get("app.max_video_duration_minutes", 30.0)
    video_duration_sec = None
    
    if not is_part:  # Só divide se não for uma parte
        try:
            # Tenta obter duração via ffprobe (mais rápido que carregar áudio completo)
            try:
                from long_video.utils import ffprobe_duration
                video_duration_sec = ffprobe_duration(f)
            except:
                # Fallback: usa pydub (mais lento mas funciona)
                from pydub import AudioSegment
                video_audio = AudioSegment.from_file(f)
                video_duration_sec = len(video_audio) / 1000.0
            
            if video_duration_sec and video_duration_sec > (max_duration_minutes * 60):
                logger.info(f"📐 Vídeo grande detectado ({video_duration_sec/60:.1f} min > {max_duration_minutes} min)")
                logger.info("🔄 Dividindo automaticamente em partes menores (procurando pausas naturais)...")
                
                # Importa funções de divisão
                try:
                    from long_video.split import split_video_into_parts
                    from long_video.utils import safe_run
                    from pathlib import Path
                    import shutil
                    
                    # Divide o vídeo em partes
                    base = os.path.splitext(os.path.basename(f))[0]
                    parts = split_video_into_parts(f, os.path.dirname(os.path.abspath(f)))
                    
                    if not parts or len(parts) == 0:
                        logger.warning("⚠️ Não foi possível dividir o vídeo. Continuando com processamento normal...")
                    elif len(parts) == 1:
                        logger.info("✅ Vídeo não precisa ser dividido. Continuando normalmente...")
                    else:
                        logger.info(f"✅ Vídeo dividido em {len(parts)} partes")
                        
                        # Processa cada parte
                        dubbed_parts = []
                        for idx, part in enumerate(parts, 1):
                            logger.info(f"\n🎬 Processando parte {idx}/{len(parts)}: {os.path.basename(part)}")
                            
                            # Processa esta parte chamando transcrever.py recursivamente
                            # Marca como parte para evitar divisão recursiva
                            part_env = os.environ.copy()
                            part_env["TRANSCRIBER_IS_PART"] = "1"
                            part_stdin = f"2\n{os.path.abspath(part)}\n"
                            part_process = subprocess.run(
                                [sys.executable, str(ROOT / "scripts" / "transcrever.py")],
                                input=part_stdin,
                                text=True,
                                encoding='utf-8',
                                env=part_env,
                                cwd=str(ROOT)
                            )
                            
                            if part_process.returncode != 0:
                                logger.error(f"❌ Falha ao processar parte {idx}")
                                continue
                            
                            # Localiza o vídeo dublado desta parte
                            part_stem = Path(part).stem
                            part_dubbed = str(output_file(f"{part_stem}_dublado.mp4"))
                            
                            if os.path.isfile(part_dubbed):
                                dubbed_parts.append(part_dubbed)
                                logger.info(f"✅ Parte {idx} dublada: {part_dubbed}")
                            else:
                                logger.warning(f"⚠️ Vídeo dublado da parte {idx} não encontrado")
                                
                            # Limpeza agressiva pro-ativa da parte atual (Demucs, vocais, instrumentais, tsxs VAD)
                            # Economiza GIGABYTES de hd durante vídeos longos de 4h+
                            try:
                                demucs_model = config.get("models.demucs.model", "htdemucs")
                                sep_part_dir = os.path.join(config.get("paths.separated_dir", "separated"), demucs_model, part_stem)
                                if os.path.isdir(sep_part_dir):
                                    shutil.rmtree(sep_part_dir, ignore_errors=True)
                                    logger.info(f"🧹 Limpeza Rápida: Pasta de Vocais e Fundo da parte {idx} limpa.")
                                
                                # Limpa arquivos .wav e residuais que começam com o nome da parte
                                arquivos_residuais = glob.glob(os.path.join(str(temp_dir()), f"{glob.escape(part_stem)}*.wav"))
                                for aqv in arquivos_residuais:
                                    try:
                                        os.remove(aqv)
                                    except:
                                        pass
                                
                                # Sempre limpar a pasta de TTS geradas p/ nao misturar audio de multi-vozes e não ocupar disco
                                shutil.rmtree(config.get("paths.tts_output_dir", "data/work/audios_frases_pt"), ignore_errors=True)
                                shutil.rmtree(config.get("paths.stretched_dir", "data/work/audios_frases_pt_stretched"), ignore_errors=True)
                            except Exception as e:
                                logger.debug(f"Falha não-critica ao limpar temp da parte {idx}: {e}")
                        
                        if len(dubbed_parts) == len(parts):
                            # Concatena todas as partes
                            logger.info(f"\n🔗 Concatenando {len(dubbed_parts)} partes dubladas...")
                            final_output = str(output_file(f"{base}_dublado.mp4"))
                            
                            # Cria lista de arquivos para concatenação
                            concat_list = str(temp_file("concat_temp.txt"))
                            with open(concat_list, "w", encoding="utf-8") as cf:
                                for dp in dubbed_parts:
                                    cf.write(f"file '{os.path.abspath(dp)}'\n")
                            
                            # Concatena com ffmpeg
                            concat_cmd = [
                                "ffmpeg", "-y", "-hide_banner",
                                "-f", "concat", "-safe", "0",
                                "-i", concat_list,
                                "-c", "copy",
                                final_output
                            ]
                            
                            result = subprocess.run(concat_cmd, capture_output=True, text=True)
                            os.remove(concat_list)
                            
                            if os.path.isfile(final_output) and os.path.getsize(final_output) > 0:
                                logger.info(f"✅ Vídeo final dublado criado: {final_output}")
                                
                                # Verifica se deve manter vídeos cortados
                                from config_loader import config
                                keep_cut_videos = config.get("app.keep_cut_videos", False)
                                
                                if keep_cut_videos:
                                    logger.info("💾 Mantendo vídeos cortados salvos (conforme configuração)")
                                    logger.info(f"   • {len(parts)} parte(s) original(is) mantida(s)")
                                    logger.info(f"   • {len(dubbed_parts)} parte(s) dublada(s) mantida(s)")
                                else:
                                    # Limpa arquivos temporários
                                    logger.info("🧹 Limpando arquivos temporários...")
                                    for part in parts:
                                        try:
                                            if os.path.isfile(part):
                                                os.remove(part)
                                                logger.debug(f"   Removido: {os.path.basename(part)}")
                                        except Exception as e:
                                            logger.warning(f"   Erro ao remover {part}: {e}")
                                    
                                    for dp in dubbed_parts:
                                        try:
                                            if os.path.isfile(dp):
                                                os.remove(dp)
                                                logger.debug(f"   Removido: {os.path.basename(dp)}")
                                        except Exception as e:
                                            logger.warning(f"   Erro ao remover {dp}: {e}")
                                
                                logger.info("🎉 Processo completo! Vídeo grande processado com sucesso.")
                                sys.exit(0)
                            else:
                                logger.error("❌ Falha na concatenação do vídeo final")
                        else:
                            logger.error(f"❌ Apenas {len(dubbed_parts)}/{len(parts)} partes foram processadas com sucesso")
                
                except ImportError as e:
                    logger.warning(f"⚠️ Módulos de vídeo longo não disponíveis: {e}")
                    logger.info("   Continuando com processamento normal...")
                except Exception as e:
                    logger.error(f"❌ Erro ao processar vídeo longo: {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
                    logger.info("   Continuando com processamento normal...")
        
        except Exception as e:
            logger.debug(f"Erro ao verificar duração do vídeo: {e}. Continuando normalmente...")
    
    base = os.path.splitext(os.path.basename(f))[0]
    vocals_path = os.path.join(
        config.get("paths.separated_dir", "separated"),
        config.get("models.demucs.model", "htdemucs"),
        base,
        "vocals.wav",
    )
    # Verifica se já existem chunks processados
    # Escapa caracteres especiais no nome do arquivo para uso em glob
    base_escaped = glob.escape(base)
    arquivos_vad = sorted(glob.glob(os.path.join(str(temp_dir()), f"{base_escaped}_*.wav")))
    chunks = []
    if arquivos_vad:
        logger.info(f"Encontrados {len(arquivos_vad)} arquivos segmentados. Pulando nova segmentação.")
        manifest_path = cache_file("chunks_manifest.json")
        manifest_loaded = False
        if os.path.isfile(manifest_path):
            try:
                from utils import load_json
                manifest = load_json(manifest_path)
                manifest_names = {os.path.basename(c.get("fname", "")) for c in manifest}
                vad_names = {os.path.basename(x) for x in arquivos_vad}
                if vad_names.issubset(manifest_names):
                    chunks = [
                        {**c, "temp": False}
                        for c in manifest
                        if os.path.basename(c.get("fname", "")) in vad_names and os.path.isfile(c.get("fname", ""))
                    ]
                    chunks.sort(key=lambda x: float(x.get("start", 0.0)))
                    manifest_loaded = bool(chunks)
                    if manifest_loaded:
                        logger.info("Tempos originais dos chunks restaurados do manifesto.")
            except Exception as e:
                logger.warning(f"Nao foi possivel carregar manifesto de chunks: {e}")
        if not manifest_loaded:
            logger.warning("Manifesto de chunks ausente; reconstruindo tempos por duracao acumulada.")
            tempo_acumulado = 0.0
            for fname in arquivos_vad:
                audio_seg = AudioSegment.from_file(fname)
                dur = len(audio_seg) / 1000.0
                chunks.append({"fname": fname, "start": tempo_acumulado, "end": tempo_acumulado + dur, "temp": False})
                tempo_acumulado += dur
    else:
        mark_step("demucs", "running")
        vocals_path = separar_vocals_demucs(f)
        mark_step("demucs", "done", path=os.path.abspath(vocals_path))
        copy_artifact(vocals_path, "vocals.wav")
        logger.info("Segmentando áudio de voz com VAD...")
        mark_step("vad", "running")
        chunks = dividir_audio_vad(vocals_path)
        mark_step("vad", "done", chunks=len(chunks))
    if not chunks:
        logger.warning("VAD não encontrou fala. Usando arquivo inteiro.")
        vocals_path = os.path.join(
            config.get("paths.separated_dir", "separated"),
            config.get("models.demucs.model", "htdemucs"),
            base,
            "vocals.wav",
        )
        source_audio = vocals_path if os.path.isfile(vocals_path) else f
        audio_full = AudioSegment.from_file(source_audio)
        dur_full = len(audio_full) / 1000.0
        chunks = [{"fname": source_audio, "start": 0.0, "end": dur_full, "temp": False}]
    else:
        # Validação: verifica se há gaps grandes entre chunks e cria chunks adicionais
        vocals_path_final = vocals_path if os.path.isfile(vocals_path) else f
        audio_total = AudioSegment.from_file(vocals_path_final)
        dur_total = len(audio_total) / 1000.0
        
        gaps_encontrados = []
        ultimo_fim = 0.0
        base = os.path.splitext(os.path.basename(vocals_path_final))[0]
        
        # Identifica gaps
        for chunk in chunks:
            chunk_start = chunk["start"]
            if chunk_start - ultimo_fim > 1.0:  # Gap maior que 1 segundo
                gaps_encontrados.append((ultimo_fim, chunk_start))
            ultimo_fim = chunk["end"]
        
        # Verifica gap no final
        if dur_total - ultimo_fim > 1.0:
            gaps_encontrados.append((ultimo_fim, dur_total))
        
        if gaps_encontrados:
            logger.warning(f"⚠️ Encontrados {len(gaps_encontrados)} gaps no áudio (total: {dur_total:.1f}s)")
            for gap_start, gap_end in gaps_encontrados:
                logger.warning(f"   Gap: {gap_start:.1f}s - {gap_end:.1f}s ({gap_end - gap_start:.1f}s)")
            
            # Cria chunks adicionais para os gaps (fallback para garantir cobertura completa)
            min_gap_duration = config.get("audio.vad.min_gap_duration_to_transcribe", 2.0)  # Só transcreve gaps > 2s
            chunks_gaps = []
            
            for gap_start, gap_end in gaps_encontrados:
                gap_duration = gap_end - gap_start
                if gap_duration >= min_gap_duration:
                    logger.info(f"📝 Criando chunk adicional para gap: {gap_start:.1f}s - {gap_end:.1f}s ({gap_duration:.1f}s)")
                    # Extrai o áudio do gap
                    gap_audio = audio_total[int(gap_start * 1000):int(gap_end * 1000)]
                    gap_fname = str(temp_file(f"{base}_gap_{len(chunks_gaps):03d}.wav"))
                    gap_audio.export(gap_fname, format="wav")
                    chunks_gaps.append({
                        "fname": gap_fname,
                        "start": gap_start,
                        "end": gap_end,
                        "temp": True,
                        "is_gap": True  # Marca como gap para tratamento especial
                    })
            
            # Adiciona os chunks de gaps à lista principal
            if chunks_gaps:
                chunks.extend(chunks_gaps)
                # Reordena chunks por tempo de início
                chunks.sort(key=lambda x: x["start"])
                logger.info(f"✅ Adicionados {len(chunks_gaps)} chunks para gaps (total de chunks: {len(chunks)})")
            else:
                logger.info("💡 Gaps muito pequenos (<2s) não serão transcritos separadamente")
            
            logger.info("💡 Dica: Considere reduzir 'aggressiveness' do VAD em config.yaml se muitos gaps aparecerem")
    salvar_manifesto_chunks(chunks)
    copy_artifact(cache_file("chunks_manifest.json"), "chunks_manifest.json")

    provider = get_provider_name()
    if config.get("app.offline_mode", False) and provider not in LOCAL_TRANSCRIPTION_PROVIDERS:
        logger.warning("Modo offline ativo: ignorando provedor externo e usando Whisper local.")
        provider = "local_whisper"
    idioma_config = config.get("transcription.source_language", "auto")
    idioma = None if idioma_config in (None, "", "auto") else idioma_config
    if provider in LOCAL_TRANSCRIPTION_PROVIDERS or config.get("transcription.force_local_language_detection", False):
        idioma = detectar_idioma(chunks[0]["fname"])

    data = None
    mark_step("transcription", "running", provider=provider)
    if provider not in LOCAL_TRANSCRIPTION_PROVIDERS:
        try:
            model_name = get_provider_model(provider)
            logger.info(f"Usando provedor externo de transcricao: {provider} ({model_name})")
            use_full_audio = config.get("transcription.use_full_vocals_audio", True)
            external_audio = vocals_path if use_full_audio and os.path.isfile(vocals_path) else chunks[0]["fname"]
            default_full_limit = 24 if provider == "openai" else 200
            max_full_audio_mb = float(config.get("transcription.max_full_audio_mb", default_full_limit))
            if provider == "openai":
                max_full_audio_mb = min(max_full_audio_mb, 24.0)
            max_full_audio_seconds = float(config.get("transcription.max_full_audio_seconds", 540))
            if provider in ("assemblyai", "google"):
                max_full_audio_seconds = float(config.get("transcription.max_full_audio_seconds", 3600))
            vocals_duration = None
            if use_full_audio and os.path.isfile(vocals_path):
                audio_ref = AudioSegment.from_file(vocals_path)
                vocals_duration = len(audio_ref) / 1000.0
            can_use_full_audio = (
                use_full_audio
                and os.path.isfile(vocals_path)
                and (os.path.getsize(vocals_path) / (1024 * 1024)) <= max_full_audio_mb
                and vocals_duration is not None
                and vocals_duration <= max_full_audio_seconds
            )
            if can_use_full_audio:
                data = transcrever_externo_para_json(vocals_path, idioma=idioma, start=0.0, end=vocals_duration)
            else:
                api_chunks = None
                if use_full_audio and os.path.isfile(vocals_path) and vocals_duration is not None:
                    size_mb = os.path.getsize(vocals_path) / (1024 * 1024)
                    logger.warning(
                        f"Audio vocal com {size_mb:.1f} MB e {vocals_duration/60:.1f} min excede limite "
                        f"({max_full_audio_mb:.1f} MB / {max_full_audio_seconds/60:.1f} min); usando blocos de API."
                    )
                    api_chunk_seconds = float(config.get("transcription.api_chunk_seconds", 480))
                    api_chunks = dividir_audio_api(vocals_path, max_seconds=api_chunk_seconds)
                    logger.info(f"Criados {len(api_chunks)} blocos para transcricao externa.")
                data = []
                chunks_to_transcribe = api_chunks if api_chunks else chunks
                for chunk in chunks_to_transcribe:
                    data.extend(transcrever_externo_para_json(
                        chunk["fname"],
                        idioma=idioma,
                        start=float(chunk.get("start", 0.0)),
                        end=float(chunk.get("end", 0.0)),
                    ))
                if api_chunks:
                    data = deduplicar_palavras_transcricao(data)
            logger.info(f"Transcricao externa concluida usando {provider}: {external_audio}")
            mark_step("transcription", "done", provider=provider)
        except Exception as e:
            fallback = config.get("transcription.fallback_provider", "local_whisper")
            logger.error(f"Falha na transcricao externa ({provider}): {e}")
            if fallback != "local_whisper":
                raise
            logger.warning("Usando fallback local com Whisper.")
            mark_step("transcription", "fallback", provider="local_whisper", error=str(e))

    if data is None:
        if idioma is None:
            idioma = detectar_idioma(chunks[0]["fname"])
        from model_cache import model_cache
        if provider == "local_faster_whisper":
            model_size = get_provider_model(provider)
            config._config.setdefault("models", {}).setdefault("faster_whisper", {})["size"] = model_size
            logger.info(f"Carregando Faster-Whisper ({model_size})...")
            model = model_cache.get_faster_whisper(model_size)
            data = transcrever_para_json_faster_whisper(chunks, idioma, model, traduzir_en=False)
            mark_step("transcription", "done", provider="local_faster_whisper")
        else:
            model_size = config.get("models.whisper.size", "medium")
            logger.info(f"Carregando modelo Whisper ({model_size})...")
            model = model_cache.get_whisper(model_size)
            data = transcrever_para_json(chunks, idioma, model, traduzir_en=False)
            mark_step("transcription", "done", provider="local_whisper")

    out_json = work_file("transcricao.json")
    save_json(data, out_json)
    report_path = report_file("transcription_report.json")
    gerar_relatorio_transcricao(data, report_path)
    copy_artifact(out_json, "transcricao.json")
    copy_artifact(report_path, "transcription_report.json")
    logger.info(f"✅ Transcrição salva em {out_json}")
    for c in chunks:
        if c.get("temp"):
            safe_remove(c["fname"])
    with open(video_original_file(), "w", encoding="utf-8") as f_video:
        f_video.write(f)
    logger.info("🔄 Iniciando tradução automática para português...")
    mark_step("translation", "running")
    ret = subprocess.run([sys.executable, str(ROOT / "scripts" / "traduzir_para_pt.py")], check=False, encoding='utf-8', errors='replace')
    if ret.returncode != 0:
        mark_step("translation", "error", code=ret.returncode)
        logger.error(f"❌ traduzir_para_pt.py falhou (código {ret.returncode}).")
        sys.exit(ret.returncode)
