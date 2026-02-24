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

logger = setup_logger(__name__)

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

    def save_chunk(s, e):
        chunk_audio = audio[int(s*1000):int(e*1000)]
        fname = f"{base}_{len(chunks):03d}.wav"
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
            )
        except Exception as e:
            logger.warning(f"Falha transcrição detalhada, tentando sem word_timestamps: {e}")
            result = model.transcribe(arquivo, language=idioma, task="transcribe")
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

if __name__ == "__main__":
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
        try:
            url = sys.stdin.readline().strip()
        except:
            url = input("Cole a URL do vídeo do YouTube: ").strip()
        logger.info("⏬ Baixando vídeo do YouTube...")
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
            'outtmpl': '%(title)s.%(ext)s',
            'merge_output_format': 'mp4',
            'progress_hooks': [yt_dlp_monitor],
            'noprogress': True # Esconde a barrinha poluidora do terminal do yt-dlp
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                f = ydl.prepare_filename(info)
            logger.info(f"✅ Vídeo salvo como: {f}")
        except Exception as e:
            if "403" in str(e) or "Forbidden" in str(e):
                logger.warning("⚠️ Erro 403 Forbidden retornado pelo YouTube. O yt-dlp pode estar desatualizado.")
                logger.info("🔄 Tentando atualizar o yt-dlp automaticamente...")
                subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], check=False)
                logger.info("⏬ Tentando baixar novamente...")
                import importlib
                importlib.reload(yt_dlp)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    f = ydl.prepare_filename(info)
                logger.info(f"✅ Vídeo salvo como: {f}")
            else:
                raise e
    elif escolha == "2":
        try:
            f = sys.stdin.readline().strip()
        except:
            f = input("Nome do arquivo (ex: Video.mp4): ").strip()
    else:
        logger.error("Opção inválida.")
        sys.exit(1)
    if not os.path.isfile(f):
        logger.error(f"Arquivo não encontrado: {f}")
        sys.exit(1)
        
    if os.environ.get("TRANSCRIBER_PREVIEW") == "1":
        logger.info("🧪 MODO AMOSTRA ATIVADO: Recortando os primeiros 15 segundos do vídeo...")
        preview_f = f"{os.path.splitext(f)[0]}_preview{os.path.splitext(f)[1]}"
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
                                [sys.executable, __file__],
                                input=part_stdin,
                                text=True,
                                encoding='utf-8',
                                env=part_env,
                                cwd=os.path.dirname(os.path.abspath(__file__))
                            )
                            
                            if part_process.returncode != 0:
                                logger.error(f"❌ Falha ao processar parte {idx}")
                                continue
                            
                            # Localiza o vídeo dublado desta parte
                            part_stem = Path(part).stem
                            part_dubbed = f"{part_stem}_dublado.mp4"
                            
                            if os.path.isfile(part_dubbed):
                                dubbed_parts.append(part_dubbed)
                                logger.info(f"✅ Parte {idx} dublada: {part_dubbed}")
                            else:
                                logger.warning(f"⚠️ Vídeo dublado da parte {idx} não encontrado")
                        
                        if len(dubbed_parts) == len(parts):
                            # Concatena todas as partes
                            logger.info(f"\n🔗 Concatenando {len(dubbed_parts)} partes dubladas...")
                            final_output = f"{base}_dublado.mp4"
                            
                            # Cria lista de arquivos para concatenação
                            concat_list = os.path.join(os.path.dirname(os.path.abspath(__file__)), "concat_temp.txt")
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
    # Verifica se já existem chunks processados
    # Escapa caracteres especiais no nome do arquivo para uso em glob
    base_escaped = glob.escape(base)
    arquivos_vad = sorted(glob.glob(f"{base_escaped}_*.wav"))
    chunks = []
    if arquivos_vad:
        logger.info(f"Encontrados {len(arquivos_vad)} arquivos segmentados. Pulando nova segmentação.")
        tempo_acumulado = 0.0
        for fname in arquivos_vad:
            audio_seg = AudioSegment.from_file(fname)
            dur = len(audio_seg) / 1000.0
            chunks.append({"fname": fname, "start": tempo_acumulado, "end": tempo_acumulado + dur, "temp": False})
            tempo_acumulado += dur
    else:
        vocals_path = separar_vocals_demucs(f)
        logger.info("Segmentando áudio de voz com VAD...")
        chunks = dividir_audio_vad(vocals_path)
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
                    gap_fname = f"{base}_gap_{len(chunks_gaps):03d}.wav"
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
    idioma = detectar_idioma(chunks[0]["fname"])
    model_size = config.get("models.whisper.size", "medium")
    logger.info(f"Carregando modelo Whisper ({model_size})...")
    from model_cache import model_cache
    model = model_cache.get_whisper(model_size)
    data = transcrever_para_json(chunks, idioma, model, traduzir_en=False)
    out_json = "transcricao.json"
    save_json(data, out_json)
    logger.info(f"✅ Transcrição salva em {out_json}")
    for c in chunks:
        if c.get("temp"):
            safe_remove(c["fname"])
    with open("video_original.txt", "w", encoding="utf-8") as f_video:
        f_video.write(f)
    logger.info("🔄 Iniciando tradução automática para português...")
    subprocess.run([sys.executable, "traduzir_para_pt.py"], check=False, encoding='utf-8', errors='replace')