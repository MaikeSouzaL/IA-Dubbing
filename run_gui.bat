@echo off
echo Iniciando Interface do Sistema de Dublagem...
if exist "%~dp0tools\ffmpeg\bin\ffmpeg.exe" set "PATH=%~dp0tools\ffmpeg\bin;%PATH%"
call .venv\Scripts\activate
python scripts\gui.py
pause
