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

Set-Location $root
Say 'Раздача роликов через телеграм-бота'

# [string[]] здесь обязателен. Без него PowerShell разворачивает массив из
# одного элемента в строку, и дальше $command[0] даёт не 'gui', а первую букву
# 'g' — программа получала аргументы по одной букве и отказывалась запускаться.
[string[]]$command = if ($args.Count -gt 0) { $args } else { @('gui') }

$python = Find-Python
if (-not $python) {
    # Ставить Python отсюда программа не берётся намеренно. Скрипт, который
    # скачивает исполняемый файл и запускает его без спроса, защита Windows
    # разбирать не станет — она пометит весь архив, и до установки дело даже
    # не дойдёт. Поэтому Python ставится обычным путём, руками и один раз.
    Fail @"
Python не найден, а поставить его отсюда нельзя.

Возьмите его на python.org/downloads, при установке отметьте галочку
«Add python.exe to PATH» — и запустите run.bat снова.

Если рядом стоит автомонтаж и он работает, Python у вас уже есть: значит он
просто не прописан в PATH. Тогда проще переустановить его с этой галочкой.
"@
}
Say "Python: $python"

if (-not (Test-Path $venvPython)) {
    Step 'Создаю окружение (один раз)'
    & $python -m venv $venv
    if (-not (Test-Path $venvPython)) {
        Fail @"
Не удалось создать окружение .venv.

Проверьте вручную, что скажет Python:
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
    & $venvPython -m pip install -r (Join-Path $root 'requirements.txt')

    if ($LASTEXITCODE -ne 0) {
        Fail @"
Зависимости не поставились. Что было — записано в файле установки, путь ниже.

Попробовать руками можно так:
    .venv\Scripts\python.exe -m pip install -r requirements.txt
"@
    }
    Get-Content (Join-Path $root 'requirements.txt') -Raw | Set-Content $stamp -NoNewline
}

# Поддержка socks-прокси ставится отдельной командой, а не вместе с остальными:
# см. requirements.txt, там объяснено почему.
if ($command[0] -eq 'socks') {
    Step 'Ставлю поддержку socks-прокси'
    & $venvPython -m pip install "aiohttp-socks>=0.8,<1"
    if ($LASTEXITCODE -ne 0) {
        Fail 'Поставить не вышло. Обычный прокси http работает и без этого.'
    }
    Write-Host "`nГотово. Теперь в поле «Прокси» можно писать socks5://…" -ForegroundColor Green
    try { Stop-Transcript | Out-Null } catch { }
    Read-Host 'Нажмите Enter' | Out-Null
    exit 0
}

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
