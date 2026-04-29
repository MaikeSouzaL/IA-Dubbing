from pydub import AudioSegment
import os
import json
import subprocess
import re
import sys
import glob
from logger import setup_logger, log_progress
from job_manager import copy_artifact, mark_step
from project_paths import ROOT as PROJECT_ROOT
from project_paths import ensure_project_dirs, output_file, pipeline_file, temp_file, video_original_file, work_file

logger = setup_logger(__name__)
ROOT = str(PROJECT_ROOT)
ensure_project_dirs()

def stretch_audio_ffmpeg(input_file, output_file, src_duration, target_duration, min_rate=1.0):
    # Calcula rate ideal
    if target_duration <= 0:
        print("⚠️ Slot de tempo inválido; mantendo áudio original para não cortar fala.")
        AudioSegment.from_wav(input_file).export(output_file, format="wav")
        return

    rate = src_duration / max(target_duration, 0.01)
    if rate < min_rate:
        print(f"⚠️ Rate {rate:.2f}x baixo demais, adicionando silêncio ao final.")
        seg = AudioSegment.from_wav(input_file)
        silence = AudioSegment.silent(duration=int((target_duration - src_duration) * 1000))
        seg = seg + silence
        seg.export(output_file, format="wav")
        return
    # Stretch normal via ffmpeg
    # (faz em múltiplas passadas se necessário)
    rates = []
    while rate > 2.0:
        rates.append(2.0)
        rate /= 2.0
    while rate < 0.5:
        rates.append(0.5)
        rate /= 0.5
    rates.append(rate)
    filter_str = ",".join([f"atempo={r:.5f}" for r in rates])
    cmd = ["ffmpeg", "-y", "-i", input_file, "-filter:a", filter_str, output_file]
    ret = subprocess.run(cmd, check=False)
    if ret.returncode != 0 or not os.path.isfile(output_file):
        print("⚠️ Falha ao ajustar velocidade; mantendo áudio original para não cortar fala.")
        AudioSegment.from_wav(input_file).export(output_file, format="wav")


def get_video_duration(video_path):
    result = subprocess.run(['ffmpeg', '-i', video_path], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    output = result.stderr.decode()
    matches = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', output)
    if matches:
        h, m, s = matches.groups()
        return int(h) * 3600 + int(m) * 60 + float(s)
    return None

def detectar_onset_offset_audio(audio_seg, threshold_db=-38):
    chunk_size = 15  # ms
    chunks = [audio_seg[i:i+chunk_size] for i in range(0, len(audio_seg), chunk_size)]
    inicio_real, fim_real = 0, len(audio_seg)
    for i, chunk in enumerate(chunks):
        if chunk.dBFS > threshold_db:
            inicio_real = i * chunk_size
            break
    for i in range(len(chunks)-1, -1, -1):
        if chunks[i].dBFS > threshold_db:
            fim_real = (i+1) * chunk_size
            break
    return inicio_real, min(fim_real, len(audio_seg))

# === CONFIGURAÇÕES ===
from config_loader import config

tts_dir = config.get("paths.tts_output_dir", "audios_frases_pt")
stretched_dir = config.get("paths.stretched_dir", "data/work/audios_frases_pt_stretched")
os.makedirs(stretched_dir, exist_ok=True)

# Lê o nome do vídeo original do arquivo
with open(video_original_file(), "r", encoding="utf-8") as f:
    video_filename = f.read().strip()
video_stem = os.path.splitext(os.path.basename(video_filename))[0]  # << fix

# 1. Carrega as frases e tempos
with open(pipeline_file("frases_pt.json"), "r", encoding="utf-8") as f:
    frases = json.load(f)

# 2. Refina cada frase e garante áudio exato ao tempo do slot
# Modificação da função que processa cada frase para melhor sincronização
def refinar_e_ajustar_frase(frase, i, adiantar_ms=120, folga_ms=0):
    """
    Refina o áudio da frase com tempos precisos:
    - Começa alguns milissegundos antes
    - Dá um pequeno respiro no final
    - Ajusta a velocidade sem cortar finais de fala
    """
    audio_in = os.path.join(tts_dir, f"frase_{i:03d}.wav")
    audio_out = os.path.join(stretched_dir, f"frase_{i:03d}.wav")
    
    if not os.path.exists(audio_in):
        print(f"Arquivo não encontrado: {audio_in}")
        return None
    
    # Carrega o áudio
    seg = AudioSegment.from_wav(audio_in)
    
    # Detecta início/fim real da fala (remove silêncio)
    inicio_ms, fim_ms = detectar_onset_offset_audio(seg, threshold_db=-38)
    seg_ref = seg[inicio_ms:fim_ms]
    
    # Threshold mais permissivo para não perder frases válidas
    threshold_db_min = -50  # Mais permissivo que -45
    threshold_duration_min = 50  # Menor que 80ms
    
    if len(seg_ref) < threshold_duration_min:
        print(f"⚠️ Frase {i} muito curta ({len(seg_ref)}ms), mas mantendo para evitar gap")
        # Não retorna None, mantém o áudio mesmo que curto
    elif seg_ref.dBFS < threshold_db_min:
        print(f"⚠️ Frase {i} com volume baixo ({seg_ref.dBFS:.1f}dB), mas mantendo para evitar gap")
        # Não retorna None, mantém o áudio mesmo que baixo
    
    # Log detalhado para debug
    if len(seg_ref) < 80 or seg_ref.dBFS < -45:
        print(f"   Duração: {len(seg_ref)}ms, Volume: {seg_ref.dBFS:.1f}dB")
    
    # Adiciona fade suave nas pontas sem apagar finais curtos de palavra.
    fade_in_ms = min(10, max(0, len(seg_ref) // 8))
    fade_out_ms = min(8, max(0, len(seg_ref) // 10))
    seg_ref = seg_ref.fade_in(fade_in_ms).fade_out(fade_out_ms)
    
    # Tempo disponível para a frase (ligeiramente menor que o intervalo total)
    # Adiantamos o início e deixamos folga no final
    target_start = max(0.0, frase["start"] - adiantar_ms/1000.0)  # Começamos X ms antes
    target_end = frase["end"] + folga_ms/1000.0  # Podemos dar respiro no final sem cortar fala
    target_duration = target_end - target_start
    
    # Arquivo temporário para stretching
    temp_stretch_file = str(temp_file(f"temp_stretch_{i}.wav"))
    seg_ref.export(temp_stretch_file, format="wav")
    
    # Duração original do áudio sem silêncio
    src_duration = len(seg_ref) / 1000.0
    
    # Aplicamos o stretching para encaixar exatamente no tempo disponível
    stretch_audio_ffmpeg(temp_stretch_file, audio_out, src_duration, target_duration)
    
    os.remove(temp_stretch_file)
    return {
        **frase, 
        "audio_path": audio_out, 
        "real_start": target_start,
        "real_end": target_end
    }

frases_refinadas = []
frases_puladas = []
log_progress(logger, 90.0)
lead_ms = int(config.get("sync.lead_ms", 80))
tail_padding_ms = int(config.get("sync.tail_padding_ms", 120))
for i, frase in enumerate(frases):
    frase_refinada = refinar_e_ajustar_frase(frase, i, adiantar_ms=lead_ms, folga_ms=tail_padding_ms)
    if frase_refinada:
        frases_refinadas.append(frase_refinada)
        print(f"✅ {frase_refinada['audio_path']} ajustado de {frase['start']:.2f}-{frase['end']:.2f} para {frase_refinada['real_start']:.2f}-{frase_refinada['real_end']:.2f}")
    else:
        # Registra frases puladas para análise
        frases_puladas.append({
            "indice": i,
            "start": frase.get("start", 0),
            "end": frase.get("end", 0),
            "texto": (frase.get("frase_pt") or "")[:50] + "..." if len(frase.get("frase_pt") or "") > 50 else (frase.get("frase_pt") or "")
        })

# Log de frases puladas
if frases_puladas:
    print(f"\n⚠️ ATENÇÃO: {len(frases_puladas)} frases foram puladas/ignoradas:")
    for fp in frases_puladas[:10]:  # Mostra até 10 primeiras
        print(f"   Frase {fp['indice']}: {fp['start']:.1f}s-{fp['end']:.1f}s - '{fp['texto']}'")
    if len(frases_puladas) > 10:
        print(f"   ... e mais {len(frases_puladas) - 10} frases")
    print(f"💡 Isso pode causar gaps no vídeo final. Verifique os logs acima para detalhes.\n")

# 3. Montagem final: cada frase começa no seu tempo; se a fala for maior,
# preservamos o final em vez de cortar. Pode haver pequena sobreposição.
video_dur = get_video_duration(video_filename)
canvas_ms = int(video_dur * 1000) if video_dur is not None else 0
for frase in frases_refinadas:
    audio_len = len(AudioSegment.from_wav(frase["audio_path"]))
    canvas_ms = max(canvas_ms, int(frase["real_start"] * 1000) + audio_len)
final_voice = AudioSegment.silent(duration=canvas_ms)

# Validação: verifica se há gaps não cobertos pelas frases refinadas
if frases_refinadas:
    ultimo_fim_ms = 0
    gaps_detectados = []
    overlaps_detectados = []
    
    for i, frase in enumerate(frases_refinadas):
        start_ms = max(0, int(frase["real_start"] * 1000))
        
        # Detecta gaps antes desta frase
        if start_ms > ultimo_fim_ms:
            gap_dur = start_ms - ultimo_fim_ms
            if gap_dur > 500:  # Gap maior que 500ms
                gaps_detectados.append((ultimo_fim_ms / 1000.0, start_ms / 1000.0, gap_dur / 1000.0))
        elif start_ms < ultimo_fim_ms:
            overlaps_detectados.append((start_ms / 1000.0, ultimo_fim_ms / 1000.0, (ultimo_fim_ms - start_ms) / 1000.0))
        
        seg = AudioSegment.from_wav(frase["audio_path"])
        final_voice = final_voice.overlay(seg, position=start_ms)
        ultimo_fim_ms = max(ultimo_fim_ms, start_ms + len(seg))
    
    # Verifica gap no final
    if video_dur is not None:
        final_ms = int(video_dur * 1000)
        if len(final_voice) < final_ms:
            gap_final = (final_ms - len(final_voice)) / 1000.0
            if gap_final > 0.5:
                gaps_detectados.append((ultimo_fim_ms / 1000.0, video_dur, gap_final))
            final_voice += AudioSegment.silent(duration=final_ms - len(final_voice))
    
    # Log de gaps detectados
    if gaps_detectados:
        print(f"\n⚠️ GAPS DETECTADOS no áudio final ({len(gaps_detectados)} gaps):")
        for gap_start, gap_end, gap_dur in gaps_detectados:
            print(f"   Gap: {gap_start:.1f}s - {gap_end:.1f}s ({gap_dur:.1f}s)")
        print(f"💡 Esses gaps serão preenchidos com silêncio. Considere revisar a transcrição.\n")
    if overlaps_detectados:
        print(f"\n⚠️ Sobreposições preservadas para evitar corte de fala ({len(overlaps_detectados)} trechos):")
        for overlap_start, overlap_end, overlap_dur in overlaps_detectados[:10]:
            print(f"   Sobreposição: {overlap_start:.1f}s - {overlap_end:.1f}s ({overlap_dur:.1f}s)")
        if len(overlaps_detectados) > 10:
            print(f"   ... e mais {len(overlaps_detectados) - 10} sobreposições")
        print("💡 Se isso acontecer muito, reduza o tamanho das frases ou ajuste os parametros de sincronizacao.\n")
else:
    print("❌ ERRO: Nenhuma frase foi refinada! Verifique os logs acima.")
    # Cria áudio vazio do tamanho do vídeo
    if video_dur is not None:
        final_voice = AudioSegment.silent(duration=int(video_dur * 1000))

voz_dublada_path = work_file("voz_dublada.wav")
final_voice.export(voz_dublada_path, format="wav")
copy_artifact(voz_dublada_path, "voz_dublada.wav")
print("✅ voz_dublada.wav criada com encaixe perfeito de slots!")

# 4. Juntar com o som de fundo (accompaniment)
bg = None
bg_dir = os.path.join(config.get("paths.separated_dir", "data/work/separated"), "htdemucs", video_stem)

def carregar_fundo(bg_dir):
    """
    Carrega o áudio de fundo (música, aplausos, sons ambiente).
    Tenta 3 estratégias diferentes de carregamento:
    1. Stems 4-canais (vocals, bass, drums, other)
    2. Stems 2-canais (vocals, no_vocals)
    3. Arquivo direto
    """
    
    if not os.path.isdir(bg_dir):
        print(f"❌ Diretório não encontrado: {bg_dir}")
        return None
    
    # Listas os arquivos disponíveis
    files_in_dir = os.listdir(bg_dir)
    print(f"📂 Arquivos em {bg_dir}: {files_in_dir}")
    
    # Estratégia 1: Tenta carregar stems separados (modelo 4-stems)
    stems = []
    for name in ["other.wav", "drums.wav", "bass.wav"]:
        path = os.path.join(bg_dir, name)
        if os.path.isfile(path):
            try:
                seg = AudioSegment.from_wav(path)
                stems.append((name, seg))
                print(f"   ✅ Carregado {name} ({len(seg)}ms)")
            except Exception as e:
                print(f"   ⚠️ Erro ao carregar {name}: {e}")
    
    if stems:
        bg_mix = stems[0][1]
        for name, s in stems[1:]:
            bg_mix = bg_mix.overlay(s)
        print(f"✅ Fundo preparado com {len(stems)} stems: {', '.join(n[1] for n in [(n, n) for n, _ in stems])}")
        return bg_mix
    
    # Estratégia 2: Fallback para no_vocals.wav (modelo 2-stems)
    no_vocals = os.path.join(bg_dir, "no_vocals.wav")
    if os.path.isfile(no_vocals):
        try:
            bg_mix = AudioSegment.from_wav(no_vocals)
            print(f"✅ Fundo carregado de no_vocals.wav ({len(bg_mix)}ms)")
            return bg_mix
        except Exception as e:
            print(f"⚠️ Erro ao carregar no_vocals.wav: {e}")
    
    # Estratégia 3: Procura por qualquer arquivo .wav que não seja vocals
    for fname in files_in_dir:
        if fname.endswith(".wav") and "vocal" not in fname.lower():
            fpath = os.path.join(bg_dir, fname)
            try:
                bg_mix = AudioSegment.from_wav(fpath)
                print(f"✅ Fundo carregado de {fname} ({len(bg_mix)}ms)")
                return bg_mix
            except Exception as e:
                print(f"⚠️ Erro ao carregar {fname}: {e}")
    
    return None

bg = carregar_fundo(bg_dir)

if bg is not None:
    # Ajuste de volumes para inteligibilidade
    bg_vol = float(config.get("audio.bg_volume", -6.0))
    final_voice_adj = final_voice + 3  # aumenta voz em +3dB
    bg_adj = bg + bg_vol               # aplica o volume de fundo customizado

    # Garante que os dois áudios têm o mesmo tamanho
    if len(bg_adj) < len(final_voice_adj):
        bg_adj = bg_adj + AudioSegment.silent(duration=(len(final_voice_adj) - len(bg_adj)))
    elif len(bg_adj) > len(final_voice_adj):
        bg_adj = bg_adj[:len(final_voice_adj)]

    # Mix simples: voz sobre fundo
    mix = bg_adj.overlay(final_voice_adj)
    audio_mix_path = work_file("audio_final_mix.wav")
    mix.export(audio_mix_path, format="wav")
    copy_artifact(audio_mix_path, "audio_final_mix.wav")
    print("✅ audio_final_mix.wav criada com voz dublada + som de fundo!")
    print(f"   Voz: +3dB | Fundo: {bg_vol}dB")
    log_progress(logger, 95.0)
else:
    # Se não encontrou, tenta buscar em subdiretórios
    print("⚠️ Som de fundo não encontrado em:", bg_dir)
    print("   Procurando em subdiretórios de 'separated/'...")
    
    separated_dirs = glob.glob(os.path.join(config.get("paths.separated_dir", "data/work/separated"), "htdemucs", "*"))
    if separated_dirs:
        print(f"   Diretórios encontrados: {separated_dirs}")
        bg_dir = separated_dirs[0]  # Usa o primeiro encontrado
        bg = carregar_fundo(bg_dir)
        
        if bg is not None:
            print(f"✅ Som de fundo encontrado em: {bg_dir}")
            bg_vol = float(config.get("audio.bg_volume", -6.0))
            final_voice_adj = final_voice + 3
            bg_adj = bg + bg_vol
            
            if len(bg_adj) < len(final_voice_adj):
                bg_adj = bg_adj + AudioSegment.silent(duration=(len(final_voice_adj) - len(bg_adj)))
            elif len(bg_adj) > len(final_voice_adj):
                bg_adj = bg_adj[:len(final_voice_adj)]
            
            mix = bg_adj.overlay(final_voice_adj)
            audio_mix_path = work_file("audio_final_mix.wav")
            mix.export(audio_mix_path, format="wav")
            copy_artifact(audio_mix_path, "audio_final_mix.wav")
            print("✅ audio_final_mix.wav criada com voz dublada + som de fundo!")
            log_progress(logger, 95.0)
        else:
            print("❌ Nenhum som de fundo encontrado em nenhum subdiretório.")
            print("   Verifique se o Demucs foi executado corretamente.")
    else:
        print("❌ Nenhum diretório 'separated/' encontrado.")

# 5. Juntar áudio final com o vídeo original usando ffmpeg
video_dublado = None  # << evita NameError
audio_final_mix_path = work_file("audio_final_mix.wav")
if os.path.isfile(audio_final_mix_path):
    video_dublado = str(output_file(f"{video_stem}_dublado.mp4"))
    cmd_ffmpeg = [
        "ffmpeg", "-y",
        "-i", video_filename,
        "-i", str(audio_final_mix_path),
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        video_dublado,
    ]
    print("\nGerando vídeo dublado automaticamente...")
    subprocess.run(cmd_ffmpeg, check=False)
    print(f"\nProcesso finalizado! Arquivo gerado: {video_dublado}")
    copy_artifact(video_dublado, video_dublado)
    mark_step("sync", "done", output=os.path.abspath(video_dublado))
    log_progress(logger, 100.0)
    
    # 6. Geração de Legendas (Se solicitado)
    if config.get("app.generate_subtitles", True):
        print("\n📝 Gerando legendas SRT...")
        subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "gerar_legendas.py")], check=False, cwd=ROOT)

else:
    print("⚠️ Não foi possível gerar o vídeo dublado pois o áudio final não foi encontrado.")

print("🚀 Pipeline completo!")

if config.get("app.clean_after_completion", True):
    # Chama automaticamente o script de limpeza
    print("🧹 Limpando arquivos temporários e intermediários...")
    subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "limpar_projeto.py")], check=False, cwd=ROOT)
else:
    print("🧹 Limpeza automática desativada (app.clean_after_completion=false).")

print("=" * 60)
print("🎉 PROCESSO COMPLETO FINALIZADO!")
print("=" * 60)
if video_dublado and os.path.isfile(video_dublado):
    size_mb = os.path.getsize(video_dublado) / (1024 * 1024)
    print(f"✅ Vídeo dublado criado: {video_dublado}")
    print(f"📊 Tamanho: {size_mb:.1f} MB")
    print(f"🎬 Pronto para assistir!")
print("=" * 60)
