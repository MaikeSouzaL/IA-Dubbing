@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Instalador - Transcrever Hind
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" (
  echo Instalacao terminou com erro. Codigo: %EXIT_CODE%
  pause
  exit /b %EXIT_CODE%
)

echo Instalacao concluida.
echo Para abrir a interface, execute: run_gui.bat
pause
exit /b 0
