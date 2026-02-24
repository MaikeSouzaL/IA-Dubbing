# ==============================================================================================
# SCRIPT DE INSTALACAO COMPLETO (ONE-CLICK) - AI DUBBING STUDIO
# 
# Funcionalidades Inclusas:
# - Verifica e Baixa Python Silenciosamente
# - Verifica e Baixa FFmpeg Silenciosamente (Joga no C:\ e seta no PATH)
# - Instala git-scm
# - Cria VirtualEnv Limpa
# - Clona o Repositorio TTS do Coqui-ai
# - Instala todos os requerimentos do Pipeline em lote (PyTorch, Whisper, Demucs, ffmpeg-python)
# ==============================================================================================

# Executa como Administrador, essencial para instalar coisas e mexer no PATH do Windows
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Voce nao esta executando como Administrador!"
    Write-Warning "Isso e necessario para instalar bibliotecas globais como o FFmpeg C++."
    Write-Host "Pressione Enter para reiniciar o script com privilegios de Administrador..."
    Read-Host
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

Clear-Host
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "                AI DUBBING STUDIO - INSTALACAO COMPLETA                         " -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

$global_path = [Environment]::GetEnvironmentVariable("Path", "Machine")

# ==========================================
# 1. PYTHON CHECK E DOWNLOAD
# ==========================================
Write-Host "[1/5] Verificando Python 3.10+..." -ForegroundColor Yellow
$pythonExists = Get-Command "python" -ErrorAction SilentlyContinue
if (-not $pythonExists) {
    Write-Host " > Python nao encontrado. Iniciando Download Silencioso do Python 3.10..." -ForegroundColor Yellow
    $pythonUrl = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
    $pythonInstaller = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonInstaller
    
    Write-Host " > Instalando Python silenciosamente. Aguarde (Pode levar alguns minutos)..." -ForegroundColor Yellow
    Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" -Wait
    Write-Host " > Python instalado e adicionado ao diretorio PATH!" -ForegroundColor Green
    
    # Atualiza a variavel de sessao pra reconhecer o python na hora
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User") 
} else {
    Write-Host " > OK! Python ja esta instalado." -ForegroundColor Green
}

# ==========================================
# 2. GIT CHECK
# ==========================================
Write-Host "`n[2/5] Verificando GIT (Necessario p/ clonar o TTS)..." -ForegroundColor Yellow
$gitExists = Get-Command "git" -ErrorAction SilentlyContinue
if (-not $gitExists) {
    Write-Host " > Git nao encontrado. Por favor baixe o instalador no site (https://git-scm.com/download/win)" -ForegroundColor Red
    Write-Host " Ou instale-o e abra o script novamente." -ForegroundColor Red
    Read-Host "Pressione Enter caso voce queira continuar de forma fragil sem o GIT"
} else {
    Write-Host " > OK! Git ja instalado." -ForegroundColor Green
}

# ==========================================
# 3. FFMPEG CHECK E INSTALACAO SILENCIOSA
# ==========================================
Write-Host "`n[3/5] Verificando FFmpeg (Necessario para audio e video)..." -ForegroundColor Yellow
$ffmpegExists = Get-Command "ffmpeg" -ErrorAction SilentlyContinue

if (-not $ffmpegExists) {
    Write-Host " > FFmpeg nao detectado." -ForegroundColor Yellow
    Write-Host " > Iniciando Download do Binario do FFmpeg direto do Github..." -ForegroundColor Yellow
    
    $ffmpegZipUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    $ffmpegZipPath = "$env:TEMP\ffmpeg.zip"
    Invoke-WebRequest -Uri $ffmpegZipUrl -OutFile $ffmpegZipPath
    
    Write-Host " > Extraindo FFmpeg para C:\ffmpeg ..." -ForegroundColor Yellow
    Expand-Archive -Path $ffmpegZipPath -DestinationPath "$env:TEMP\ffmpeg-extracted" -Force
    
    # Renomeia ou Move a pasta para um local definitivo (C:\ffmpeg)
    if (Test-Path "C:\ffmpeg") { Remove-Item -Recurse -Force "C:\ffmpeg" }
    Move-Item -Path "$env:TEMP\ffmpeg-extracted\ffmpeg-master-latest-win64-gpl" -Destination "C:\ffmpeg" -Force
    
    # Colocar C:\ffmpeg\bin no PATH do Windows usando Registro pra fixar
    $ffmpegBinPath = "C:\ffmpeg\bin"
    if ($global_path -notmatch [regex]::Escape($ffmpegBinPath)) {
        Write-Host " > Adicionando o binario C:\ffmpeg\bin as Variaveis de Ambiente Globais..." -ForegroundColor Yellow
        [Environment]::SetEnvironmentVariable("Path", $global_path + ";" + $ffmpegBinPath, "Machine")
        $env:Path += ";$ffmpegBinPath"
    }
    
    # Limpeza
    Remove-Item $ffmpegZipPath -Force
    Remove-Item -Recurse -Force "$env:TEMP\ffmpeg-extracted"
    
    Write-Host " > OK! FFmpeg instalado maravilhosamente bem!" -ForegroundColor Green
} else {
    Write-Host " > OK! FFmpeg ja esta instalado e configurado no PATH." -ForegroundColor Green
}


# ==========================================
# 4. CRIANDO AMBIENTE VIRTUAL (VENV)
# ==========================================
Write-Host "`n[4/5] Configurando Ambiente Virtual Python (vEnv)..." -ForegroundColor Yellow
$venvDir = "venv"
if (-not (Test-Path $venvDir)) {
    Write-Host " > Criando ambiente virtual..." -ForegroundColor Yellow
    python -m venv $venvDir
    Write-Host " > OK! Ambiente criado." -ForegroundColor Green
} else {
    Write-Host " > OK! Ambiente virtual ja existente." -ForegroundColor Green
}


# ==========================================
# 5. PIPELINE: DEPENDENCIAS GIGANTES
# ==========================================
Write-Host "`n[5/5] Instalando todas as bibliotecas pesadas de Inteligencia Artificial..." -ForegroundColor Yellow
Write-Host " -> PyTorch, Whisper, Demucs, Pydub, etc." -ForegroundColor Cyan
Write-Host " (Isso pode demorar de 2 a 15 minutos dependendo da sua internet)" -ForegroundColor Cyan

# Caminho para o executavel PIP de dentro do VirtualEnv (Garante isolamento absoluto)
$pipPath = ".\$venvDir\Scripts\pip.exe"

# Atualizar Pip primeiro pra nao dar pau em libs novas
& $pipPath install --upgrade pip

# Verifica se existe o Requirements original do projeto
if (Test-Path "requirements.txt") {
    Write-Host " > Instalando pacotes do requirements.txt..." -ForegroundColor Yellow
    
    # Usa Invoke-Expression ou execucao direta (com redirecionamento de erro pra ver ao vivo se quiser)
    & $pipPath install -r requirements.txt
    
} else {
    Write-Host " > Nao achei o requirements.txt, mas vou tentar instalar os modulos na unha!" -ForegroundColor Yellow
    & $pipPath install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
    & $pipPath install openai-whisper
    & $pipPath install demucs
    & $pipPath install pydub
    & $pipPath install ffmpeg-python
    & $pipPath install webrtcvad
    Write-Host " > E o famigerado TTS (Coqui-AI)" -ForegroundColor Yellow
    & $pipPath install git+https://github.com/coqui-ai/TTS.git
}

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "                      🎉 INSTALACAO CONCLUIDA COM SUCESSO! 🎉                 " -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " 1. O Python agora esta instalado!"
Write-Host " 2. O FFmpeg profissional foi embutido no seu Windows!"
Write-Host " 3. A pasta VENV baixou dezenas de Gibabytes de Inteligencia Artificial."
Write-Host ""
Write-Host " AGORA ESTA TUDO PRONTO PARA O SHOW!" -ForegroundColor Yellow
Write-Host " Clique no arquivo 'iniciar_projeto.bat' (o azulzinho) para abrir a interface gráfica."
Write-Host " Ou, abra um terminal novo na pasta e rode:"
Write-Host " > venv\Scripts\activate"
Write-Host " > python gui.py"
Write-Host "================================================================================" -ForegroundColor Cyan

Read-Host "Pressione ENTER para fechar a tela..."
