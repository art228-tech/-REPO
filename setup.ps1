#requires -Version 5.1
<#
    Установка и запуск в один щелчок.

    Находит Python, при необходимости ставит его, делает отдельное окружение,
    ставит зависимости и открывает окно программы. Всё лежит рядом с этим
    файлом: в системе ничего не меняется, удаление — это удаление папки.
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$cache = Join-Path $root '.cache'

# Всё, что происходит при установке, пишется в файл. Ошибка уезжает вверх за
# край окна быстрее, чем человек успевает её прочитать, а пересказать её по
# памяти нельзя — этот файл можно просто переслать.
$logDir = Join-Path $root 'данные\журналы'
$installLog = Join-Path $logDir 'установка.log'
try {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Transcript -Path $installLog -Force | Out-Null
} catch { }

# PowerShell по умолчанию считает вывод в поток ошибок настоящей ошибкой, а pip
# пишет туда предупреждения. Без этого установка падала бы на первом же из них.
$PSDefaultParameterValues['*:ErrorAction'] = 'Continue'

function Say($text)  { Write-Host $text }
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Warn($text) { Write-Host $text -ForegroundColor Yellow }
function Fail($text) {
    Write-Host "`n$text" -ForegroundColor Red
    Write-Host "`nВесь ход установки записан в файл:"
    Write-Host "  $installLog"
    Write-Host 'Его можно переслать — по нему видно, что именно не вышло.'
    try { Stop-Transcript | Out-Null } catch { }
    Write-Host "`nОкно не закроется, пока вы не нажмёте Enter."
    Read-Host | Out-Null
    exit 1
}

function Test-Antivirus($text) {
    # Windows Defender удаляет файл и пишет про «вирус или потенциально
    # нежелательную программу». Установка после этого обрывается на месте, а
    # человек видит только «команда не найдена» и не понимает, при чём тут он.
    return $text -match 'вирус|потенциально нежелательн|virus|unwanted software|Operation did not complete'
}

function Test-Python($exe) {
    if (-not $exe) { return $false }
    try {
        $out = & $exe -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
        return ($LASTEXITCODE -eq 0) -and ([int]$out -ge 310)
    } catch { return $false }
}

function Find-Python {
    foreach ($candidate in @('py -3.12', 'py -3.11', 'py -3', 'python3', 'python')) {
        $parts = $candidate.Split(' ')
        $exe = (Get-Command $parts[0] -ErrorAction SilentlyContinue)
        if (-not $exe) { continue }

        if ($parts.Count -gt 1) {
            try {
                $real = & $exe.Source $parts[1] -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and (Test-Python $real)) { return $real }
            } catch { }
        } elseif (Test-Python $exe.Source) {
            return $exe.Source
        }
    }

    foreach ($guess in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe")) {
        if ((Test-Path $guess) -and (Test-Python $guess)) { return $guess }
    }
    return $null
}

function Install-Python {
    Step 'Ставлю Python'

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say 'Пробую через встроенный установщик Windows...'
        winget install --id Python.Python.3.12 --scope user --silent `
            --accept-package-agreements --accept-source-agreements | Out-Null
        $found = Find-Python
        if ($found) { return $found }
        Warn 'Встроенный установщик не справился, качаю с python.org.'
    }

    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $installer = Join-Path $cache 'python-installer.exe'
    $url = 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe'

    Say "Качаю $url"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    } catch {
        Fail @"
Не удалось скачать Python: $($_.Exception.Message)

Поставьте его руками с https://www.python.org/downloads/ (отметьте галочку
«Add python.exe to PATH») и запустите run.bat снова.
"@
    }

    Say 'Устанавливаю (без прав администратора, только для вас)...'
    $process = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1',
        'Include_test=0', 'Include_tcltk=1')
    if ($process.ExitCode -ne 0) {
        Fail "Установщик Python вернул код $($process.ExitCode). Поставьте Python руками с python.org."
    }

    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')

    $found = Find-Python
    if (-not $found) {
        Fail 'Python установился, но не нашёлся. Перезапустите run.bat — иногда помогает.'
    }
    Remove-Item $installer -Force -ErrorAction SilentlyContinue
    return $found
}

Set-Location $root
Say 'Раздача роликов через телеграм-бота'

# [string[]] здесь обязателен. Без него PowerShell разворачивает массив из
# одного элемента в строку, и дальше $command[0] даёт не 'gui', а первую букву
# 'g' — программа получала аргументы по одной букве и отказывалась запускаться.
[string[]]$command = if ($args.Count -gt 0) { $args } else { @('gui') }

$python = Find-Python
if (-not $python) {
    Say 'Python не найден.'
    $python = Install-Python
}
Say "Python: $python"

if (-not (Test-Path $venvPython)) {
    Step 'Создаю окружение (один раз)'
    & $python -m venv $venv
    if (-not (Test-Path $venvPython)) {
        Fail @"
Не удалось создать окружение .venv.

Чаще всего это антивирус или отсутствие модуля venv. Проверьте вручную:
    $python -m venv .venv
"@
    }
}

$stamp = Join-Path $venv '.зависимости'
$needs = $true
if (Test-Path $stamp) {
    $installed = Get-Content $stamp -Raw -ErrorAction SilentlyContinue
    $wanted = Get-Content (Join-Path $root 'requirements.txt') -Raw
    $needs = ($installed -ne $wanted)
}

if ($needs) {
    Step 'Ставлю зависимости (несколько десятков мегабайт, один раз)'
    & $venvPython -m pip install --upgrade pip --quiet
    $pip = & $venvPython -m pip install -r (Join-Path $root 'requirements.txt') 2>&1
    $pip | ForEach-Object { Write-Host $_ }

    if ($LASTEXITCODE -ne 0) {
        if (Test-Antivirus ($pip -join "`n")) {
            Fail @"
Установку прервал антивирус: он принял один из пакетов за нежелательную
программу и удалил файл на лету.

Что делать:
  1. Откройте «Безопасность Windows» - «Защита от вирусов и угроз» -
     «Журнал защиты» и посмотрите, что именно он забрал.
  2. Там же можно нажать «Действия» - «Разрешить на устройстве».
  3. Или добавьте папку программы в исключения:
     «Параметры» - «Исключения» - «Добавить исключение» - «Папка».

После этого удалите папку .venv рядом с программой и запустите run.bat снова.
"@
        }
        Fail @"
Зависимости не поставились.

Обычно это интернет или прокси. Попробуйте руками:
    .venv\Scripts\python.exe -m pip install -r requirements.txt
"@
    }
    Get-Content (Join-Path $root 'requirements.txt') -Raw | Set-Content $stamp -NoNewline
}

# Отдельная команда: поставить поддержку socks-прокси. Вынесена из обязательных
# потому, что антивирусы Windows принимают этот пакет за нежелательную
# программу и обрывают вместе с ним всю установку.
if ($command[0] -eq 'socks') {
    Step 'Ставлю поддержку socks-прокси'
    & $venvPython -m pip install "aiohttp-socks>=0.8,<1"
    if ($LASTEXITCODE -ne 0) {
        Fail @"
Поставить не вышло. Чаще всего мешает антивирус: он принимает этот пакет за
нежелательную программу. Добавьте папку программы в исключения и повторите.

Обычный прокси http работает и без него.
"@
    }
    Write-Host "`nГотово. Теперь в поле «Прокси» можно писать socks5://…" -ForegroundColor Green
    try { Stop-Transcript | Out-Null } catch { }
    Read-Host 'Нажмите Enter' | Out-Null
    exit 0
}

if (Test-Path $cache) { Remove-Item $cache -Recurse -Force -ErrorAction SilentlyContinue }

Step 'Запускаю'

# Запускается обычный python, а не pythonw, и консоль остаётся открытой рядом с
# окном программы. Так сделано намеренно: pythonw не показывает ни консоли, ни
# ошибок, и упавшая на запуске программа оставляла человека перед пустым
# экраном — ровно это и случилось. Лишнее окно консоли — небольшая плата за то,
# что причина сбоя всегда на виду.
$started = Get-Date
# Дальше работает сама программа, и свой журнал она ведёт отдельно. Запись хода
# установки на этом заканчивается, иначе файл рос бы всё время работы бота.
try { Stop-Transcript | Out-Null } catch { }

& $venvPython (Join-Path $root 'main.py') @command
$code = $LASTEXITCODE
$spent = ((Get-Date) - $started).TotalSeconds

if ($code -ne 0) {
    Write-Host "`nПрограмма завершилась с кодом $code. Причина выше." -ForegroundColor Yellow
    Write-Host "Подробности лежат в: данные\журналы\сбой.txt"
    Write-Host 'Окно не закроется, пока вы не нажмёте Enter.'
    Read-Host | Out-Null
} elseif ($command[0] -eq 'gui' -and $spent -lt 5) {
    # Окно, закрывшееся за пять секунд, никто не закрывал руками — значит оно
    # и не открылось. Молча гасить консоль в этом случае нельзя: со стороны это
    # выглядит как «запустил, мигнуло и ничего не произошло», и разбираться
    # снова будет не по чему.
    Write-Host "`nПрограмма закрылась через $([int]$spent) с, хотя ошибки не было." `
        -ForegroundColor Yellow
    Write-Host 'Похоже, окно не открылось. Загляните в: данные\журналы'
    Write-Host 'Окно не закроется, пока вы не нажмёте Enter.'
    Read-Host | Out-Null
}
exit $code
