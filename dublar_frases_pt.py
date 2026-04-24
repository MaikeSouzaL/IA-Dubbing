import os
import json
import re
import sys
import time
from pydub import AudioSegment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "TTS"))
from TTS.api import TTS
import subprocess
import torch

from config_loader import config
from logger import setup_logger, log_progress
from utils import load_json, save_json, ensure_dir
from voice_manager import voice_manager
from job_manager import copy_artifact, mark_step

logger = setup_logger(__name__)

# Importa o deep-translator se for necessário gerar frases_pt
try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

def sanitize_text_for_tts(text):
    """
    Sanitiza texto para TTS, removendo caracteres problemáticos.
    Remove apenas caracteres inválidos, NÃO limita comprimento.
    """
    if not text:
        return ""
    
    # Remove caracteres de controle e caracteres unicode problemáticos
    text = ''.join(char for char in text if char.isprintable() or char in '\n\r\t')
    
    # Substitui múltiplas vírgulas ou pontos por um único
    text = re.sub(r',{2,}', ',', text)
    text = re.sub(r'\.{4,}', '...', text)  # Preserva reticências mas limita
    
    # Remove espaços extras
    text = ' '.join(text.split())
    
    return text.strip()


def split_long_text(text, max_length=250):
    """
    Quebra texto longo em múltiplas partes de forma inteligente.
    
    Args:
        text: Texto a ser quebrado
        max_length: Tamanho máximo de cada parte (padrão: 250 caracteres)
        
    Returns:
        Lista de strings, cada uma com no máximo max_length caracteres
        
    Prioridade de quebra:
    1. Ponto final, ponto de exclamação, ponto de interrogação
    2. Ponto e vírgula
    3. Vírgula
    4. Espaço
    """
    if not text or len(text) <= max_length:
        return [text] if text else []
    
    parts = []
    remaining = text
    
    while len(remaining) > max_length:
        # Tenta quebrar no melhor ponto dentro do limite
        best_break = -1
        
        # 1. Procura ponto final, !, ?
        for punct in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
            pos = remaining.rfind(punct, 0, max_length)
            if pos > max_length // 3:  # Só aceita se for pelo menos 1/3 do comprimento
                best_break = pos + len(punct)
                break
        
        # 2. Se não encontrou, procura ponto e vírgula
        if best_break == -1:
            pos = remaining.rfind('; ', 0, max_length)
            if pos > max_length // 3:
                best_break = pos + 2
        
        # 3. Se não encontrou, procura vírgula
        if best_break == -1:
            pos = remaining.rfind(', ', 0, max_length)
            if pos > max_length // 3:
                best_break = pos + 2
        
        # 4. Se não encontrou, quebra no último espaço
        if best_break == -1:
            pos = remaining.rfind(' ', 0, max_length)
            if pos > 0:
                best_break = pos + 1
            else:
                # Última opção: quebra forçada no limite
                best_break = max_length
        
        # Adiciona a parte
        part = remaining[:best_break].strip()
        if part:
            parts.append(part)
        
        # Atualiza o texto restante
        remaining = remaining[best_break:].strip()
    
    # Adiciona o que sobrou
    if remaining:
        parts.append(remaining)
    
    return parts

def split_sentences(transcript):
    frases = re.split(r'(?<=[.!?।])\s+', transcript)
    return [f.strip() for f in frases if f.strip()]

def criar_referencia_voz_limpa(vocals_path):
    if not config.get("models.tts.clean_voice_reference", True) or not os.path.isfile(vocals_path):
        return vocals_path
    try:
        audio = AudioSegment.from_file(vocals_path)
        target_ms = int(float(config.get("models.tts.voice_reference_seconds", 18)) * 1000)
        threshold = float(config.get("models.tts.voice_reference_threshold_db", -35))
        selected = AudioSegment.silent(duration=0)
        for pos in range(0, len(audio), 500):
            chunk = audio[pos:pos + 500]
            if chunk.dBFS != float("-inf") and chunk.dBFS >= threshold:
                selected += chunk
                if len(selected) >= target_ms:
                    break
        if len(selected) < 3000:
            return vocals_path
        out = "voice_reference_clean.wav"
        selected[:target_ms].fade_in(20).fade_out(60).export(out, format="wav")
        logger.info(f"✅ Referencia de voz limpa criada: {out} ({len(selected[:target_ms])/1000:.1f}s)")
        return out
    except Exception as e:
        logger.warning(f"Nao foi possivel criar referencia de voz limpa: {e}")
        return vocals_path

def alinhar_frases_palavras(frases, words):
    if not frases or not words:
        return []
    alinhadas = []
    w_idx = 0
    w_len = len(words)
    for frase in frases:
        tokens = frase.split()
        if not tokens:
            continue
        start_idx = w_idx
        consumed = 0
        while w_idx < w_len and consumed < len(tokens):
            consumed += 1
            w_idx += 1
        if start_idx >= w_len:
            break
        end_idx = min(w_idx - 1, w_len - 1)
        start = float(words[start_idx].get("start", 0.0))
        end = float(words[end_idx].get("end", start))
        if end < start:
            end = start
        alinhadas.append({"frase": frase, "start": start, "end": end})
    return alinhadas

def gerar_frases_pt(transcricao_json, frases_pt_json):
    if GoogleTranslator is None:
        raise RuntimeError("Instale deep-translator: pip install deep-translator")
    
    data = load_json(transcricao_json)
    
    target_lang = config.get("translation.target_language", "pt")
    translator = GoogleTranslator(source='auto', target=target_lang)
    
    frases_pt = []
    for chunk in data:
        transcript = (chunk.get("transcript") or "").strip()
        words = chunk.get("words", []) or []
        if not transcript:
            continue
        frases = split_sentences(transcript)
        frases_tempo = alinhar_frases_palavras(frases, words) if words else []
        for frase_info in frases_tempo:
            origem = frase_info["frase"]
            try:
                frase_pt = translator.translate(origem) if origem else ""
            except Exception as e:
                logger.error(f"Falha tradução '{origem[:40]}': {e}")
                frase_pt = origem
            frases_pt.append({
                "frase_pt": frase_pt,
                "frase_original": origem,
                "start": frase_info["start"],
                "end": frase_info["end"]
            })
    
    save_json(frases_pt, frases_pt_json)
    logger.info(f"✅ {len(frases_pt)} frases salvas em {frases_pt_json}")

def dublar_frases(frases_pt_json, vocals_path, saida_dir, use_multi_voice=False):
    """
    Dubla frases com TTS, suportando múltiplas vozes e tratamento robusto de erros.
    
    Args:
        frases_pt_json: Caminho para arquivo de frases
        vocals_path: Voz padrão (usado se multi-voice estiver desabilitado)
        saida_dir: Diretório de saída
        use_multi_voice: Se True, usa voice_manager para vozes por falante
    """
    frases = load_json(frases_pt_json)
    
    # Seleciona dispositivo
    device_config = config.get("models.tts.device", "auto")
    if device_config == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = device_config
    
    logger.info(f"Usando dispositivo: {device}")
    
    # Verifica se há múltiplos falantes
    if use_multi_voice:
        speakers = set(f.get("speaker", "SPEAKER_00") for f in frases)
        logger.info(f"🎭 Modo multi-voz ativado: {len(speakers)} falantes detectados")
        
        voices = voice_manager.get_all_voices()
        if not voices:
            logger.warning("⚠️ Nenhuma referência de voz configurada. Usando voz padrão.")
            use_multi_voice = False
        else:
            logger.info(f"✅ Referências de voz carregadas: {', '.join(voices.keys())}")
    
    # Limpa VRAM antes de começar
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        logger.debug("🧹 VRAM inicial limpa")
    
    model_name = config.get("models.tts.model_name", "tts_models/multilingual/multi-dataset/xtts_v2")
    fallback_model = config.get("models.tts.fallback_model", "tts_models/en/vctk/vits")
    
    from model_cache import model_cache
    
    try:
        tts = model_cache.get_tts(model_name, device)
    except Exception as e:
        logger.error(f"XTTS falhou: {e} -> fallback para {fallback_model}")
        model_name = fallback_model
        tts = model_cache.get_tts(model_name, device)
    
    ensure_dir(saida_dir)
    
    clear_cache_freq = config.get("models.tts.gpu_clear_cache_frequency", 50)
    max_retries = 3  # Número máximo de tentativas por frase
    cuda_broken = False  # Flag: contexto CUDA corrompido → fallback CPU
    
    total_frases = len(frases)
    
    for i, frase in enumerate(frases):
        # Progresso de 35 a 85%
        percent = 35.0 + (i / total_frases) * 50.0
        log_progress(logger, percent)
        
        texto = (frase.get("frase_pt") or "").strip()
        if not texto:
            logger.warning(f"⚠️ [{i+1}/{total_frases}] Frase vazia (start: {frase.get('start', 0):.1f}s, end: {frase.get('end', 0):.1f}s) - SERÁ PULADA")
            logger.warning(f"   Isso pode causar um gap no vídeo final!")
            continue
        
        # SANITIZA O TEXTO (remove caracteres inválidos, MAS NÃO trunca)
        texto_original = texto
        texto = sanitize_text_for_tts(texto)
        if not texto:
            logger.warning(f"⚠️ [{i+1}/{total_frases}] Texto vazio após sanitização, pulando")
            continue
        
        audio_path = os.path.join(saida_dir, f"frase_{i:03d}.wav")
        
        # Pula se já existe
        if os.path.isfile(audio_path):
            logger.info(f"⏭️ [{i+1}/{total_frases}] Pulando (já existe)")
            continue
        
        # QUEBRA TEXTOS LONGOS EM MÚLTIPLAS PARTES
        max_chars = config.get("models.tts.max_chars_per_chunk", 250)
        text_parts = split_long_text(texto, max_length=max_chars)
        
        if len(text_parts) > 1:
            logger.info(f"📝 [{i+1}/{total_frases}] Texto longo ({len(texto)} chars) quebrado em {len(text_parts)} partes")
            for idx, part in enumerate(text_parts):
                logger.debug(f"   Parte {idx+1}/{len(text_parts)}: {part[:60]}...")
        
        # LIMPA VRAM ANTES DE CADA SÍNTESE
        if device == "cuda" and not cuda_broken:
            try:
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                if i % clear_cache_freq == 0:
                    try:
                        vram_used = torch.cuda.memory_allocated() / 1024**2
                        vram_total = torch.cuda.get_device_properties(0).total_memory / 1024**2
                        logger.debug(f"📊 VRAM: {vram_used:.1f}/{vram_total:.1f} MB")
                    except Exception:
                        pass
            except Exception as _ec:
                logger.warning(f"⚠️ CUDA corrompido detectado antes da frase {i+1} — migrando para CPU: {_ec}")
                cuda_broken = True
                device = "cpu"
                try:
                    model_cache.clear_memory()
                    tts = model_cache.get_tts(model_name, "cpu")
                    logger.info("✅ Modelo TTS recarregado na CPU — continuando.")
                except Exception as _el:
                    logger.error(f"❌ Falha ao recarregar TTS na CPU: {_el}")
        
        # Determina qual voz usar
        voice_ref = vocals_path
        
        if use_multi_voice and "xtts" in model_name:
            speaker = frase.get("speaker", "SPEAKER_00")
            voice_data = voice_manager.get_voice(speaker)
            
            if voice_data:
                voice_ref = voice_data["audio_path"]
                voice_name = voice_data.get("name", speaker)
                logger.debug(f"🎤 Usando voz: {voice_name}")
            else:
                logger.warning(f"⚠️ Voz não encontrada para {speaker}, usando padrão")
        
        # PROCESSA CADA PARTE DO TEXTO
        audio_segments = []
        all_success = True
        
        for part_idx, text_part in enumerate(text_parts):
            # Caminho temporário para cada parte (se houver múltiplas)
            if len(text_parts) > 1:
                part_audio_path = os.path.join(saida_dir, f"frase_{i:03d}_part{part_idx}.wav")
            else:
                part_audio_path = audio_path
            
            kwargs = {"text": text_part, "file_path": part_audio_path}
            
            # Passe 'language' e 'speaker_wav' somente quando usando XTTS
            if "xtts" in model_name:
                kwargs["language"] = config.get("translation.target_language", "pt")
                if os.path.isfile(voice_ref):
                    kwargs["speaker_wav"] = voice_ref
            
            # RETRY LOOP para lidar com erros CUDA temporários
            success = False
            for retry in range(max_retries):
                try:
                    tts.tts_to_file(**kwargs)
                    
                    if len(text_parts) == 1:
                        speaker_info = f" ({frase.get('speaker', 'default')})" if use_multi_voice else ""
                        logger.info(f"✅ [{i+1}/{total_frases}]{speaker_info} {text_part[:50]}...")
                    else:
                        logger.debug(f"   ✅ Parte {part_idx+1}/{len(text_parts)} processada")
                    
                    success = True
                    break
                    
                except RuntimeError as e:
                    error_str = str(e).lower()
                    is_cuda_err = "cuda" in error_str or "out of memory" in error_str or "assert" in error_str
                    if is_cuda_err:
                        logger.error(f"❌ Erro CUDA na frase {i} parte {part_idx} (tentativa {retry+1}/{max_retries}): {e}")
                        logger.debug(f"   Texto: {text_part[:100]}...")
                        
                        # Tenta recuperar CUDA; se falhar, migra para CPU
                        recovered = False
                        if not cuda_broken:
                            try:
                                torch.cuda.empty_cache()
                                torch.cuda.synchronize()
                                torch.cuda.reset_peak_memory_stats()
                                time.sleep(0.5)
                                recovered = True
                            except Exception as e2:
                                logger.warning(f"⚠️ Contexto CUDA irrecuperável: {e2}")
                                cuda_broken = True
                        
                        if cuda_broken or not recovered:
                            # Migra para CPU e recarrega o modelo
                            logger.info("🔄 Migrando para CPU e recarregando modelo TTS...")
                            device = "cpu"
                            try:
                                model_cache.clear_memory()
                                tts = model_cache.get_tts(model_name, "cpu")
                                logger.info("✅ Modelo TTS recarregado na CPU")
                                # Atualiza kwargs para CPU (remove speaker_wav se necessário)
                                kwargs["file_path"] = part_audio_path
                            except Exception as e3:
                                logger.error(f"❌ Falha ao recarregar na CPU: {e3}")
                                break
                        elif retry == max_retries - 1:
                            logger.info("🔄 Última tentativa - recarregando modelo TTS na GPU...")
                            try:
                                model_cache.clear_memory()
                                torch.cuda.empty_cache()
                                tts = model_cache.get_tts(model_name, device)
                                logger.info("✅ Modelo TTS recarregado na GPU")
                            except Exception as e3:
                                logger.error(f"❌ Falha ao recarregar: {e3}")
                    else:
                        logger.error(f"❌ Erro TTS na frase {i} parte {part_idx}: {e}")
                        break  # Não é erro CUDA, não vale a pena retry
                        
                except Exception as e:
                    logger.error(f"❌ Erro TTS na frase {i} parte {part_idx}: {e}")
                    break
            
            if success:
                # Carrega o áudio gerado
                try:
                    seg = AudioSegment.from_file(part_audio_path)
                    audio_segments.append(seg)
                except Exception as e:
                    logger.error(f"❌ Erro ao carregar áudio da parte {part_idx}: {e}")
                    all_success = False
                    break
            else:
                all_success = False
                break
        
        # Se processou múltiplas partes, concatena os áudios
        if all_success and len(text_parts) > 1:
            try:
                # Concatena todos os segmentos com pequena pausa entre eles
                pause_ms = 100  # 100ms de pausa entre partes
                final_audio = audio_segments[0]
                
                for seg in audio_segments[1:]:
                    final_audio = final_audio + AudioSegment.silent(duration=pause_ms) + seg
                
                # Salva o áudio final
                final_audio.export(audio_path, format="wav")
                
                # Remove arquivos temporários das partes
                for part_idx in range(len(text_parts)):
                    part_audio_path = os.path.join(saida_dir, f"frase_{i:03d}_part{part_idx}.wav")
                    if os.path.exists(part_audio_path):
                        os.remove(part_audio_path)
                
                logger.info(f"✅ [{i+1}/{total_frases}] {len(text_parts)} partes concatenadas ({len(texto)} chars total)")
                
            except Exception as e:
                logger.error(f"❌ Erro ao concatenar partes da frase {i}: {e}")
                all_success = False
        
        if all_success:
            # Registra duração do áudio gerado
            try:
                seg = AudioSegment.from_file(audio_path)
                frase["tts_dur"] = len(seg)/1000.0
            except:
                frase["tts_dur"] = 0.0
        else:
            logger.warning(f"⚠️ Frase {i} falhou após {max_retries} tentativas")
    
    # Limpeza final
    if device == "cuda" and not cuda_broken:
        try:
            torch.cuda.empty_cache()
            logger.debug("🧹 VRAM final limpa")
        except Exception:
            pass
    
    log_progress(logger, 85.0)
    
    # Atualiza frases_pt.json com tts_dur
    save_json(frases, frases_pt_json)
    copy_artifact(frases_pt_json, "frases_pt.json")
    mark_step("tts", "done", total=total_frases)
    
    logger.info("✅ Dublagem concluída. Durações registradas.")

if __name__ == "__main__":
    try:
        with open("video_original.txt", "r", encoding="utf-8") as f_video:
            video = f_video.read().strip()
    except Exception as e:
        logger.error(f"❌ Falha ao ler video_original.txt: {e}")
        sys.exit(1)
        
    base = os.path.splitext(os.path.basename(video))[0]
    
    # Caminhos
    sep_dir = config.get("paths.separated_dir", "separated")
    demucs_model = config.get("models.demucs.model", "htdemucs")
    vocals = os.path.join(sep_dir, demucs_model, base, "vocals.wav")
    
    transcricao = "transcricao.json"
    frases_pt = "frases_pt.json"
    saida_audios = config.get("paths.tts_output_dir", "audios_frases_pt")
    
    if not os.path.isfile(frases_pt):
        gerar_frases_pt(transcricao, frases_pt)
    else:
        logger.info(f"✔ Reaproveitando {frases_pt}")
        
    if not os.path.isfile(vocals):
        # Tenta achar em qualquer lugar
        import glob
        found = glob.glob(f"**/{base}/vocals.wav", recursive=True)
        if found:
            vocals = found[0]
            logger.info(f"🎤 Usando referência encontrada: {vocals}")
        else:
            logger.warning("⚠️ Sem vocals.wav: dublagem sem clonagem.")
    else:
        logger.info(f"🎤 Usando referência: {vocals}")
    vocals = criar_referencia_voz_limpa(vocals)
    
    # Verifica se deve usar multi-voice
    use_multi_voice = config.get("app.use_multi_voice", False)
    
    # Se multi-voice ativado, executa diarização primeiro
    if use_multi_voice:
        logger.info("🎭 Multi-voice ativado, executando diarização...")
        from speaker_diarization import perform_speaker_diarization, assign_speakers_to_phrases
        
        num_speakers = config.get("app.expected_speakers", None)
        diarization = perform_speaker_diarization(vocals, num_speakers)
        
        if diarization:
            assign_speakers_to_phrases(frases_pt, diarization)
            logger.info("✅ Diarização e atribuição concluídas")
        else:
            logger.warning("⚠️ Diarização falhou, usando modo single-voice")
            use_multi_voice = False
        
    dublar_frases(frases_pt, vocals, saida_audios, use_multi_voice=use_multi_voice)
    
    logger.info("🔄 Sincronizando e juntando...")
    mark_step("sync", "running")
    ret = subprocess.run([sys.executable, "sincronizar_e_juntar.py"], encoding='utf-8', errors='replace')
    if ret.returncode != 0:
        mark_step("sync", "error", code=ret.returncode)
        logger.error(f"❌ sincronizar_e_juntar.py retornou código {ret.returncode}")
        sys.exit(ret.returncode)
