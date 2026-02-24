@echo off
setlocal

echo Ativando o ambiente virtual...
call venv\Scripts\activate || (echo ERRO: venv nao encontrada. & pause & exit /b 1)

echo Atualizando pip/setuptools/wheel...
python -m pip install -U pip setuptools wheel

echo Instalando dependencias do projeto (se houver)...
if exist requirements.txt (
  python -m pip install -r requirements.txt
)

echo Instalando dependencias do TTS...
if exist TTS\requirements.txt (
  pushd TTS
  python -m pip install -r requirements.txt
  python -m pip install -e .
  popd
)

REM >>> Linha chave para resolver o import do TTS
set "PYTHONPATH=%CD%\TTS;%PYTHONPATH%"

echo Instalando pacotes extras...
python -m pip install -U yt-dlp deep-translator pydub webrtcvad demucs openai-whisper

echo Iniciando pipeline...
python transcrever.py

echo.
echo Processo concluido.
pause
