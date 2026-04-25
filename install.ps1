param(
    [switch]$SkipTTS,
    [switch]$DownloadTestModels,
    [string]$PreloadModels = "",
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$PythonWingetId = "Python.Python.3.10"
$GitWingetId = "Git.Git"
$TtsRepo = "https://github.com/coqui-ai/TTS.git"
$TtsCommit = "dbf1a08a0d4e47fdad6172e433eeb34bc6b13b4e"
$FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Require-Command($Name, $InstallHint) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "$Name nao encontrado. $InstallHint"
    }
    return $cmd.Source
}

function Find-Python310 {
    $py = Get-Command "py" -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3.10 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @($py.Source, "-3.10")
        }
    }

    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @($python.Source)
        }
    }

    $known = @(
        "$env:LocalAppData\Programs\Python\Python310\python.exe",
        "$env:ProgramFiles\Python310\python.exe",
        "${env:ProgramFiles(x86)}\Python310\python.exe"
    )
    foreach ($candidate in $known) {
        if (Test-Path $candidate) {
            & $candidate -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                return @($candidate)
            }
        }
    }

    return $null
}

function Install-Python310 {
    $winget = Get-Command "winget" -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.10 nao encontrado e winget nao esta disponivel. Instale Python 3.10 manualmente."
    }
    Write-Step "Python 3.10 nao encontrado. Instalando automaticamente via winget"
    Invoke-Checked $winget.Source @(
        "install",
        "--id", $PythonWingetId,
        "--exact",
        "--source", "winget",
        "--accept-source-agreements",
        "--accept-package-agreements"
    )
}

function Find-Or-Install-Git {
    $git = Get-Command "git" -ErrorAction SilentlyContinue
    if ($git) {
        return $git.Source
    }

    $winget = Get-Command "winget" -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Git nao encontrado e winget nao esta disponivel. Instale Git for Windows manualmente."
    }

    Write-Step "Git nao encontrado. Instalando automaticamente via winget"
    Invoke-Checked $winget.Source @(
        "install",
        "--id", $GitWingetId,
        "--exact",
        "--source", "winget",
        "--accept-source-agreements",
        "--accept-package-agreements"
    )

    $git = Get-Command "git" -ErrorAction SilentlyContinue
    if ($git) {
        return $git.Source
    }

    $known = @(
        "$env:ProgramFiles\Git\cmd\git.exe",
        "${env:ProgramFiles(x86)}\Git\cmd\git.exe"
    )
    foreach ($candidate in $known) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "Git foi instalado, mas ainda nao foi encontrado neste terminal. Feche e abra o terminal e rode install.bat de novo."
}

function Install-Portable-Ffmpeg {
    $toolsDir = Join-Path $Root "tools"
    $ffmpegDir = Join-Path $toolsDir "ffmpeg"
    $ffmpegExe = Join-Path $ffmpegDir "bin\ffmpeg.exe"
    $ffprobeExe = Join-Path $ffmpegDir "bin\ffprobe.exe"

    if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe)) {
        $env:PATH = "$(Split-Path $ffmpegExe);$env:PATH"
        return $ffmpegExe
    }

    Write-Step "FFmpeg nao encontrado. Baixando FFmpeg portatil para tools\ffmpeg"
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null

    $zipPath = Join-Path $toolsDir "ffmpeg-release-essentials.zip"
    $extractDir = Join-Path $toolsDir "ffmpeg_extract"

    if (Test-Path $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    if (Test-Path $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }

    Invoke-WebRequest -Uri $FfmpegUrl -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

    $downloadedFfmpeg = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if (-not $downloadedFfmpeg) {
        throw "Download do FFmpeg concluido, mas ffmpeg.exe nao foi encontrado no arquivo baixado."
    }

    $downloadedRoot = $downloadedFfmpeg.Directory.Parent.FullName
    if (Test-Path $ffmpegDir) {
        Remove-Item -LiteralPath $ffmpegDir -Recurse -Force
    }
    Move-Item -LiteralPath $downloadedRoot -Destination $ffmpegDir

    Remove-Item -LiteralPath $zipPath -Force
    if (Test-Path $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }

    if (-not ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe))) {
        throw "FFmpeg portatil foi extraido, mas binarios esperados nao foram encontrados."
    }

    $env:PATH = "$(Split-Path $ffmpegExe);$env:PATH"
    return $ffmpegExe
}

function Invoke-Checked {
    param(
        [string]$Command,
        [string[]]$CommandArgs
    )
    Write-Host ">> $Command $($CommandArgs -join ' ')" -ForegroundColor DarkGray
    & $Command @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Comando falhou ($LASTEXITCODE): $Command $($CommandArgs -join ' ')"
    }
}

Write-Host "Transcrever Hind - instalacao automatica" -ForegroundColor Green
Write-Host "Raiz do projeto: $Root"

Write-Step "Verificando ferramentas basicas"
$git = Find-Or-Install-Git
$pythonCommand = Find-Python310
if (-not $pythonCommand) {
    Install-Python310
    $pythonCommand = Find-Python310
}
if (-not $pythonCommand) {
    throw "Python 3.10 foi instalado, mas ainda nao foi encontrado neste terminal. Feche e abra o terminal e rode install.bat de novo."
}
$projectFfmpeg = Join-Path $Root "tools\ffmpeg\bin\ffmpeg.exe"
$projectFfprobe = Join-Path $Root "tools\ffmpeg\bin\ffprobe.exe"
if ((Test-Path $projectFfmpeg) -and (Test-Path $projectFfprobe)) {
    $env:PATH = "$(Split-Path $projectFfmpeg);$env:PATH"
} elseif (-not (Get-Command "ffmpeg" -ErrorAction SilentlyContinue) -or -not (Get-Command "ffprobe" -ErrorAction SilentlyContinue)) {
    Install-Portable-Ffmpeg | Out-Null
}

Write-Step "Criando ambiente virtual .venv"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $pythonExe = $pythonCommand[0]
    $pythonArgs = @()
    if ($pythonCommand.Count -gt 1) {
        $pythonArgs += $pythonCommand[1..($pythonCommand.Count - 1)]
    }
    $pythonArgs += @("-m", "venv", ".venv")
    Invoke-Checked $pythonExe $pythonArgs
}
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"

Write-Step "Atualizando pip/wheel"
Invoke-Checked $venvPython @("-m", "pip", "install", "--upgrade", "pip", "wheel")

Write-Step "Instalando dependencias Python do projeto"
Invoke-Checked $venvPython @("-m", "pip", "install", "-r", "requirements.txt")

if (-not $SkipTTS) {
    Write-Step "Preparando Coqui TTS local na raiz do projeto"
    if (-not (Test-Path "TTS\.git")) {
        if (Test-Path "TTS") {
            Write-Warning "A pasta TTS ja existe, mas nao parece ser um clone Git. Vou reaproveitar como esta."
        } else {
            Invoke-Checked $git @("clone", $TtsRepo, "TTS")
        }
    } else {
        Write-Host "TTS ja existe. Conferindo commit travado..."
    }

    if (Test-Path "TTS\.git") {
        Write-Step "Travando Coqui TTS no commit validado"
        Invoke-Checked $git @("-C", "TTS", "fetch", "--depth", "1", "origin", $TtsCommit)
        Invoke-Checked $git @("-C", "TTS", "checkout", "--detach", $TtsCommit)
    }

    if (Test-Path "TTS\requirements.txt") {
        Write-Step "Instalando dependencias do Coqui TTS"
        Invoke-Checked $venvPython @("-m", "pip", "install", "-r", "TTS\requirements.txt")
    }

    Write-Step "Instalando Coqui TTS em modo editavel"
    Invoke-Checked $venvPython @("-m", "pip", "install", "--no-deps", "-e", "TTS")

    Write-Step "Reaplicando versoes pinadas do projeto"
    Invoke-Checked $venvPython @("-m", "pip", "install", "-r", "requirements.txt")
}

Write-Step "Criando estrutura de pastas de trabalho"
$dirs = @(
    "data\inputs",
    "data\outputs",
    "data\work",
    "data\temp",
    "data\reports",
    "data\cache",
    "data\jobs",
    "logs",
    "tools"
)
foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Write-Step "Preparando arquivo .env"
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env criado a partir de .env.example"
} elseif (Test-Path ".env") {
    Write-Host ".env ja existe; mantendo configuracoes locais."
}

if ($DownloadTestModels -and -not $PreloadModels) {
    $PreloadModels = "tiny"
}

if ($PreloadModels) {
    Write-Step "Baixando/testando modelos Faster-Whisper: $PreloadModels"
    $modelsLiteral = ($PreloadModels -replace "'", "").Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $modelsPython = ($modelsLiteral | ForEach-Object { "'$_'" }) -join ", "
    $code = @"
from pathlib import Path
import sys
sys.path.insert(0, str(Path('src/transcrever_hind').resolve()))
from model_cache import model_cache
for model_name in [$modelsPython]:
    print(f'Carregando Faster-Whisper {model_name}...')
    model_cache.get_faster_whisper(model_name)
    print(f'Faster-Whisper {model_name} carregado com sucesso.')
"@
    $code | & $venvPython -
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Teste/preload do Faster-Whisper falhou. A instalacao terminou, mas confira CUDA/cuDNN."
    }
}

Write-Step "Validando instalacao"
Invoke-Checked $venvPython @("-m", "py_compile", "scripts\gui.py", "scripts\transcrever.py", "src\transcrever_hind\project_paths.py")
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) {
    Write-Warning "pip check encontrou conflitos. Veja as mensagens acima."
}

Write-Host ""
Write-Host "Instalacao finalizada!" -ForegroundColor Green
Write-Host "Abra a interface com: run_gui.bat"
Write-Host ""
Write-Host "Opcoes uteis:"
Write-Host "  install.bat -DownloadTestModels     baixa/testa um modelo tiny do Faster-Whisper"
Write-Host "  install.bat -PreloadModels tiny,large-v3-turbo"
Write-Host "  install.bat -SkipTTS                pula clone/instalacao do TTS"

if (-not $NoPause) {
    Write-Host ""
    Read-Host "Pressione Enter para sair"
}
