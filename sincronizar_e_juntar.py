from pydub import AudioSegment
import os
import json
import subprocess
import re
import sys
import glob
from logger import setup_logger, log_progress

logger = setup_logger(__name__)

def stretch_audio_ffmpeg(input_file, output_file, src_duration, target_duration, min_rate=1.0, max_rate=2.0):
    # Calcula rate ideal
    rate = src_duration / max(target_duration, 0.01)
    if rate > max_rate:
        print(f"⚠️ Rate {rate:.2f}x alto demais, cortando áudio.")
        # Apenas corta o áudio para caber
        seg = AudioSegment.from_wav(input_file)
        seg = seg[:int(target_duration * 1000)]
        seg.export(output_file, format="wav")
        return
    elif rate < min_rate:
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
    cmd = f'ffmpeg -y -i "{input_file}" -filter:a "{filter_str}" "{output_file}"'
    os.system(cmd)


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
tts_dir = "audios_frases_pt"
stretched_dir = "audios_frases_pt_stretched"
os.makedirs(stretched_dir, exist_ok=True)

# Lê o nome do vídeo original do arquivo
with open("video_original.txt", "r", encoding="utf-8") as f:
    video_filename = f.read().strip()
video_stem = os.path.splitext(os.path.basename(video_filename))[0]  # << fix

# 1. Carrega as frases e tempos
with open("frases_pt.json", "r", encoding="utf-8") as f:
    frases = json.load(f)

# 2. Refina cada frase e garante áudio exato ao tempo do slot
# Modificação da função que processa cada frase para melhor sincronização
def refinar_e_ajustar_frase(frase, i, adiantar_ms=120, folga_ms=30):
    """
    Refina o áudio da frase com tempos precisos:
    - Começa alguns milissegundos antes
    - Termina com folga para não ultrapassar o tempo
    - Ajusta a velocidade para caber perfeitamente no slot
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
    
    # Adiciona fade suave nas pontas
    seg_ref = seg_ref.fade_in(15).fade_out(18)
    
    # Tempo disponível para a frase (ligeiramente menor que o intervalo total)
    # Adiantamos o início e deixamos folga no final
    target_start = frase["start"] - adiantar_ms/1000.0  # Começamos X ms antes
    target_end = frase["end"] - folga_ms/1000.0  # Terminamos Y ms antes do fim
    target_duration = target_end - target_start
    
    # Arquivo temporário para stretching
    temp_file = f"temp_stretch_{i}.wav"
    seg_ref.export(temp_file, format="wav")
    
    # Duração original do áudio sem silêncio
    src_duration = len(seg_ref) / 1000.0
    
    # Aplicamos o stretching para encaixar exatamente no tempo disponível
    stretch_audio_ffmpeg(temp_file, audio_out, src_duration, target_duration)
    
    os.remove(temp_file)
    return {
        **frase, 
        "audio_path": audio_out, 
        "real_start": target_start,
        "real_end": target_end
    }

frases_refinadas = []
frases_puladas = []
log_progress(logger, 90.0)
for i, frase in enumerate(frases):
    frase_refinada = refinar_e_ajustar_frase(frase, i, adiantar_ms=80, folga_ms=50)
    if frase_refinada:
        frases_refinadas.append(frase_refinada)
        print(f"✅ {frase_refinada['audio_path']} ajustado de {frase['start']:.2f}-{frase['end']:.2f} para {frase_refinada['real_start']:.2f}-{frase_refinada['real_end']:.2f}")
    else:
        # Registra frases puladas para análise
        frases_puladas.append({
            "indice": i,
            "start": frase.get("start", 0),
            "end": frase.get("end", 0),
            "texto": frase.get("frase_pt", "")[:50] + "..." if len(frase.get("frase_pt", "")) > 50 else frase.get("frase_pt", "")
        })

# Log de frases puladas
if frases_puladas:
    print(f"\n⚠️ ATENÇÃO: {len(frases_puladas)} frases foram puladas/ignoradas:")
    for fp in frases_puladas[:10]:  # Mostra até 10 primeiras
        print(f"   Frase {fp['indice']}: {fp['start']:.1f}s-{fp['end']:.1f}s - '{fp['texto']}'")
    if len(frases_puladas) > 10:
        print(f"   ... e mais {len(frases_puladas) - 10} frases")
    print(f"💡 Isso pode causar gaps no vídeo final. Verifique os logs acima para detalhes.\n")

# 3. Montagem final: cada frase em seu slot exato, com silêncio entre, sem sobreposição
final_voice = AudioSegment.silent(duration=0)
video_dur = get_video_duration(video_filename)

# Validação: verifica se há gaps não cobertos pelas frases refinadas
if frases_refinadas:
    ultimo_fim_ms = 0
    gaps_detectados = []
    
    for i, frase in enumerate(frases_refinadas):
        start_ms = int(frase["real_start"] * 1000)
        
        # Detecta gaps antes desta frase
        if start_ms > ultimo_fim_ms:
            gap_dur = start_ms - ultimo_fim_ms
            if gap_dur > 500:  # Gap maior que 500ms
                gaps_detectados.append((ultimo_fim_ms / 1000.0, start_ms / 1000.0, gap_dur / 1000.0))
        
        # Garante que não volta no tempo
        if len(final_voice) < start_ms:
            final_voice += AudioSegment.silent(duration=start_ms - len(final_voice))
            
        seg = AudioSegment.from_wav(frase["audio_path"])
        final_voice += seg
        ultimo_fim_ms = len(final_voice)
    
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
else:
    print("❌ ERRO: Nenhuma frase foi refinada! Verifique os logs acima.")
    # Cria áudio vazio do tamanho do vídeo
    if video_dur is not None:
        final_voice = AudioSegment.silent(duration=int(video_dur * 1000))

final_voice.export("voz_dublada.wav", format="wav")
print("✅ voz_dublada.wav criada com encaixe perfeito de slots!")

# 4. Juntar com o som de fundo (accompaniment)
bg = None
bg_dir = os.path.join("separated", "htdemucs", video_stem)

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
    final_voice_adj = final_voice + 3  # aumenta voz em +3dB
    bg_adj = bg - 6                     # reduz som de fundo em -6dB para destacar voz

    # Garante que os dois áudios têm o mesmo tamanho
    if len(bg_adj) < len(final_voice_adj):
        bg_adj = bg_adj + AudioSegment.silent(duration=(len(final_voice_adj) - len(bg_adj)))
    elif len(bg_adj) > len(final_voice_adj):
        bg_adj = bg_adj[:len(final_voice_adj)]

    # Mix simples: voz sobre fundo
    mix = bg_adj.overlay(final_voice_adj)
    mix.export("audio_final_mix.wav", format="wav")
    print("✅ audio_final_mix.wav criada com voz dublada + som de fundo!")
    print(f"   Voz: +3dB | Fundo: -6dB")
    log_progress(logger, 95.0)
else:
    # Se não encontrou, tenta buscar em subdiretórios
    print("⚠️ Som de fundo não encontrado em:", bg_dir)
    print("   Procurando em subdiretórios de 'separated/'...")
    
    separated_dirs = glob.glob("separated/htdemucs/*")
    if separated_dirs:
        print(f"   Diretórios encontrados: {separated_dirs}")
        bg_dir = separated_dirs[0]  # Usa o primeiro encontrado
        bg = carregar_fundo(bg_dir)
        
        if bg is not None:
            print(f"✅ Som de fundo encontrado em: {bg_dir}")
            final_voice_adj = final_voice + 3
            bg_adj = bg - 6
            
            if len(bg_adj) < len(final_voice_adj):
                bg_adj = bg_adj + AudioSegment.silent(duration=(len(final_voice_adj) - len(bg_adj)))
            elif len(bg_adj) > len(final_voice_adj):
                bg_adj = bg_adj[:len(final_voice_adj)]
            
            mix = bg_adj.overlay(final_voice_adj)
            mix.export("audio_final_mix.wav", format="wav")
            print("✅ audio_final_mix.wav criada com voz dublada + som de fundo!")
            log_progress(logger, 95.0)
        else:
            print("❌ Nenhum som de fundo encontrado em nenhum subdiretório.")
            print("   Verifique se o Demucs foi executado corretamente.")
    else:
        print("❌ Nenhum diretório 'separated/' encontrado.")

# 5. Juntar áudio final com o vídeo original usando ffmpeg
video_dublado = None  # << evita NameError
if os.path.isfile("audio_final_mix.wav"):
    video_dublado = f"{video_stem}_dublado.mp4"
    cmd_ffmpeg = f'ffmpeg -y -i "{video_filename}" -i audio_final_mix.wav -c:v copy -map 0:v:0 -map 1:a:0 -shortest "{video_dublado}"'
    print("\nGerando vídeo dublado automaticamente...")
    os.system(cmd_ffmpeg)
    print(f"\nProcesso finalizado! Arquivo gerado: {video_dublado}")
    log_progress(logger, 100.0)
    
    # 6. Geração de Legendas (Se solicitado)
    from config_loader import config
    if config.get("app.generate_subtitles", True):
        print("\n📝 Gerando legendas SRT...")
        subprocess.run([sys.executable, "gerar_legendas.py"], check=False, cwd=ROOT)

else:
    print("⚠️ Não foi possível gerar o vídeo dublado pois o áudio final não foi encontrado.")

print("🚀 Pipeline completo!")

from config_loader import config
if config.get("app.clean_after_completion", True):
    # Chama automaticamente o script de limpeza
    print("🧹 Limpando arquivos temporários e intermediários...")
    ROOT = os.path.dirname(os.path.abspath(__file__))
    subprocess.run([sys.executable, "limpar_projeto.py"], check=False, cwd=ROOT)
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