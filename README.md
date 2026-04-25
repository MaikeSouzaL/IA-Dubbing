# Transcrever Hind

Projeto local para transcrever, traduzir e dublar videos com Whisper/Faster-Whisper, Demucs e Coqui TTS.

## Instalacao no Windows

1. Instale os pre-requisitos, se quiser. O instalador tenta resolver automaticamente:
   - Python 3.10 via `winget`
   - Git for Windows via `winget`
   - FFmpeg portatil em `tools/ffmpeg`

2. Clone o projeto:

```bat
git clone <URL_DO_REPOSITORIO>
cd Transcrever_hind
```

3. Rode o instalador:

```bat
install.bat
```

O instalador cria `.venv`, instala `requirements.txt`, baixa FFmpeg portatil se necessario, clona o Coqui TTS na pasta `TTS/`, trava o TTS no commit validado, instala os requirements do TTS, instala o TTS em modo editavel e cria as pastas de trabalho em `data/`.

Para tambem baixar/testar um modelo pequeno do Faster-Whisper:

```bat
install.bat -DownloadTestModels
```

Para pre-baixar modelos especificos:

```bat
install.bat -PreloadModels tiny,large-v3-turbo
```

## Abrir a interface

```bat
run_gui.bat
```

## Estrutura

```text
scripts/              atalhos executaveis
src/transcrever_hind/ codigo principal
data/inputs/          videos de entrada
data/outputs/         videos finais
data/work/            arquivos intermediarios
data/temp/            temporarios
data/cache/           cache
data/jobs/            historico de jobs
TTS/                  clone local do Coqui TTS, criado pelo instalador
tools/ffmpeg/         FFmpeg portatil, criado pelo instalador se necessario
```

## Transcricao local

Na interface, use:

```text
Transcricao: local_faster_whisper
Modelo: large-v3-turbo
```

Para GPUs com pouca VRAM, teste `turbo` ou `medium`.

## Chaves de API

Copie `.env.example` para `.env` e preencha somente se for usar provedores externos como OpenAI, Deepgram, AssemblyAI ou Google.
