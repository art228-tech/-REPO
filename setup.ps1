# Подготовка окружения и запуск программы.
#
# Вся работа вынесена сюда из .bat не случайно: cmd.exe спотыкается и на
# юниксовых переносах строк, и на кириллице внутри батника — окно просто
# закрывается без сообщения. PowerShell работает и с тем, и с другим.

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$Venv = Join-Path $Root '.venv'
$Tools = Join-Path $Root 'tools'
$Cache = Join-Path $Root '.cache'
$PyFallback = '3.12.10'
$FfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'

function Write-Step($text) { Write-Host "  $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "  $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  $text" -ForegroundColor Yellow }
function Write-Bad($text) { Write-Host "  $text" -ForegroundColor Red }

function Stop-WithMessage($lines) {
    Write-Host ''
    foreach ($line in $lines) { Write-Bad $line }
    Write-Host ''
    Read-Host 'Нажми Enter, чтобы закрыть окно' | Out-Null
    exit 1
}

# --- Python -----------------------------------------------------------------

function Invoke-Python($python, [string[]]$arguments) {
    # Расщепление работает только через переменную: @(...) передал бы массив
    # одним аргументом, и python получил бы мусор вместо ключей.
    $callArgs = @()
    if ($python.Prefix) { $callArgs += $python.Prefix }
    $callArgs += $arguments
    & $python.Exe @callArgs
}

function Test-PythonCommand($exe, $prefix) {
    try {
        $candidate = @{ Exe = $exe; Prefix = $prefix }
        $out = Invoke-Python $candidate @('-c', 'import sys;print(sys.version_info[0]*100+sys.version_info[1])') 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        if ([int]($out | Select-Object -First 1) -lt 310) { return $null }
        return $candidate
    } catch { return $null }
}

function Find-Python {
    foreach ($candidate in @(
            @{ Exe = 'py'; Prefix = '-3' },
            @{ Exe = 'python'; Prefix = $null },
            @{ Exe = 'python3'; Prefix = $null })) {
        $found = Test-PythonCommand $candidate.Exe $candidate.Prefix
        if ($found) { return $found }
    }

    # Установщик мог не обновить PATH в этом окне — смотрим обычные места.
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($base in $roots) {
        $exes = Get-ChildItem $base -Filter 'Python3*' -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName 'python.exe' } |
            Where-Object { Test-Path $_ }
        foreach ($exe in $exes) {
            $found = Test-PythonCommand $exe $null
            if ($found) { return $found }
        }
    }
    return $null
}

function Install-Python {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Step 'Пробую через встроенный установщик Windows...'
        try {
            & winget install --exact --id Python.Python.3.12 --source winget `
                --accept-source-agreements --accept-package-agreements --silent | Out-Null
        } catch { }
        if (Find-Python) { return }
    }

    Write-Step "Скачиваю установщик Python $PyFallback с python.org (около 30 МБ)..."
    New-Item -ItemType Directory -Path $Cache -Force | Out-Null
    $setup = Join-Path $Cache "python-$PyFallback-amd64.exe"
    $url = "https://www.python.org/ftp/python/$PyFallback/python-$PyFallback-amd64.exe"
    try {
        Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing
    } catch {
        Stop-WithMessage @(
            'Не удалось скачать Python. Скорее всего нет интернета или мешает антивирус.',
            'Поставь его вручную с https://www.python.org/downloads/',
            'При установке обязательно отметь галочку "Add Python to PATH".'
        )
    }

    Write-Step 'Устанавливаю Python только для тебя, права администратора не нужны...'
    $arguments = @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_pip=1',
        'Include_tcltk=1', 'Include_launcher=1', 'AssociateFiles=0', 'Shortcuts=0'
    )
    Start-Process -FilePath $setup -ArgumentList $arguments -Wait
}

# --- FFmpeg -----------------------------------------------------------------

function Get-BundledFfmpeg {
    $bin = Join-Path $Tools 'ffmpeg\bin'
    if ((Test-Path (Join-Path $bin 'ffmpeg.exe')) -and (Test-Path (Join-Path $bin 'ffprobe.exe'))) {
        return $bin
    }
    return $null
}

function Test-Ffmpeg {
    if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and
        (Get-Command ffprobe -ErrorAction SilentlyContinue)) { return $true }
    $bin = Get-BundledFfmpeg
    if ($bin) {
        $env:PATH = "$bin;$env:PATH"
        return $true
    }
    return $false
}

function Install-Ffmpeg {
    New-Item -ItemType Directory -Path $Cache -Force | Out-Null
    $zip = Join-Path $Cache 'ffmpeg.zip'

    if (-not (Test-Path $zip)) {
        Write-Step 'Скачиваю FFmpeg, около 110 МБ...'
        try {
            Invoke-WebRequest -Uri $FfmpegUrl -OutFile $zip -UseBasicParsing
        } catch {
            Stop-WithMessage @(
                'Не удалось скачать FFmpeg. Скорее всего нет интернета или мешает антивирус.',
                'Можно поставить вручную в PowerShell: winget install Gyan.FFmpeg',
                "Либо положить ffmpeg.exe и ffprobe.exe в папку: $Tools\ffmpeg\bin"
            )
        }
    }

    Write-Step 'Распаковываю...'
    $temp = Join-Path $Cache 'ffmpeg_unpack'
    if (Test-Path $temp) { Remove-Item $temp -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $temp -Force

    $exe = Get-ChildItem $temp -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
    if (-not $exe) {
        Stop-WithMessage @('В скачанном архиве нет ffmpeg.exe — попробуй удалить папку .cache и запустить заново.')
    }

    $bin = Join-Path $Tools 'ffmpeg\bin'
    New-Item -ItemType Directory -Path $bin -Force | Out-Null
    Copy-Item (Join-Path $exe.DirectoryName '*.exe') $bin -Force
    Remove-Item $temp -Recurse -Force
}

# --- Работа -----------------------------------------------------------------

Write-Host ''
Write-Host '============================================================'
Write-Host '   Сборка роликов CapCut по шаблонам'
Write-Host '   Подготовка окружения. Первый запуск - несколько минут.'
Write-Host '============================================================'
Write-Host ''

$python = Find-Python
if (-not $python) {
    Write-Step '[1/5] Python не найден, устанавливаю...'
    Install-Python
    $python = Find-Python
}
if (-not $python) {
    Stop-WithMessage @(
        'Python установился, но эта командная строка его ещё не видит.',
        'Закрой окно и запусти run.bat заново - обычно этого достаточно.',
        'Если не помогло, поставь Python вручную с https://www.python.org/downloads/',
        'и обязательно отметь галочку "Add Python to PATH".'
    )
}

$version = (Invoke-Python $python @('-c', 'import sys;print(sys.version.split()[0])') | Select-Object -First 1)
Write-Ok "[1/5] Python $version"

$hasTk = $true
try {
    Invoke-Python $python @('-c', 'import tkinter') 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $hasTk = $false }
} catch { $hasTk = $false }
if (-not $hasTk) {
    Write-Warn 'В этом Python нет tkinter, поэтому окно не откроется.'
    Write-Warn 'Переустанови Python с python.org, отметив "tcl/tk and IDLE".'
    Write-Warn 'Пока можно работать из консоли: run.bat run --help'
}

if (-not (Test-Ffmpeg)) {
    Write-Step '[2/5] FFmpeg не найден...'
    Install-Ffmpeg
    if (-not (Test-Ffmpeg)) {
        Stop-WithMessage @('FFmpeg скачался, но запустить его не удалось. Проверь антивирус.')
    }
}
Write-Ok '[2/5] FFmpeg на месте'

$venvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Step '[3/5] Создаю окружение Python...'
    Invoke-Python $python @('-m', 'venv', $Venv)
    if (-not (Test-Path $venvPython)) {
        Stop-WithMessage @(
            'Не удалось создать окружение Python.',
            'Проверь, что на диске есть свободное место и что папку не блокирует антивирус.'
        )
    }
}
Write-Ok '[3/5] Окружение готово'

$depsMark = Join-Path $Venv '.deps_ok'
if (-not (Test-Path $depsMark)) {
    Write-Step '[4/5] Ставлю зависимости. Скачается около 300 МБ, это самый долгий шаг...'
    & $venvPython -m pip install --upgrade pip --quiet --disable-pip-version-check
    & $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $Root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage @(
            'Не удалось поставить зависимости. Обычно это интернет или антивирус.',
            'Запусти run.bat заново - скачивание продолжится с того же места.'
        )
    }
    New-Item -ItemType File -Path $depsMark -Force | Out-Null
}
Write-Ok '[4/5] Зависимости на месте'

$modelMark = Join-Path $Venv '.model_ok'
if (-not (Test-Path $modelMark)) {
    Write-Step '[5/5] Скачиваю модель распознавания речи, около 250 МБ...'
    & $venvPython -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        New-Item -ItemType File -Path $modelMark -Force | Out-Null
    } else {
        Write-Warn 'Заранее скачать не получилось - программа возьмёт её при первом ролике.'
    }
}
Write-Ok '[5/5] Модель распознавания на месте'

Write-Host ''
Write-Host '============================================================'
Write-Host '   Всё готово, открываю программу'
Write-Host '============================================================'
Write-Host ''

$ErrorActionPreference = 'Continue'
$launch = @((Join-Path $Root 'main.py'))
if ($AppArgs) { $launch += $AppArgs }
& $venvPython @launch
$code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }

if ($code -ne 0) {
    Write-Host ''
    Write-Bad "Программа завершилась с ошибкой (код $code). Сообщения выше."
    Read-Host 'Нажми Enter, чтобы закрыть окно' | Out-Null
}
exit $code
