@echo off
echo Ativando o ambiente virtual...
call venv\Scripts\activate
echo.
echo Executando script de transcricao...
python transcrever.py
echo.
echo Processo concluído.
pause