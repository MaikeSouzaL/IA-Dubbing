@echo off
title Instalador e Iniciador - AI Dubbing Studio
color 0B

echo ===================================================
echo     SCRIPT DE INSTALACAO/INICIALIZACAO AUTOMATICO
echo     AI Dubbing Studio - Transcricao e Dublagem
echo ===================================================
echo.

:: Verifica se o Python ta instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado! Instale o Python 3.10 ou superior e marque "Add to PATH".
    pause
    exit /b
)

:: Verifica se a pasta venv existe
if not exist "venv\" (
    echo [INFO] Detectamos que e a primeira vez rodando o projeto.
    echo [INFO] Criando o ambiente virtual Python (venv)...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERRO] Falha ao criar ambiente virtual.
        pause
        exit /b
    )
    echo [OK] Ambiente virtual criado com sucesso!
    echo.
)

:: Ativa o ambiente virtual
echo [INFO] Ativando ambiente virtual...
call venv\Scripts\activate.bat

:: Instala as paradas se o requirements existir
if exist "requirements.txt" (
    echo [INFO] Verificando e instalando dependencias (pode demorar na primeira vez)...
    echo.
    python -m pip install --upgrade pip >nul 2>&1
    pip install -r requirements.txt
    echo.
    echo [OK] Bibliotecas testadas/atualizadas!
) else (
    echo [AVISO] O arquivo requirements.txt nao foi encontrado.
)

echo.
echo ===================================================
echo     INICIANDO A INTERFACE GRAFICA...
echo ===================================================
echo.
python gui.py

pause
