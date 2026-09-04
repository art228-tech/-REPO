@echo off
setlocal EnableExtensions
REM ============================================================
REM  Drop this .bat into a folder with .txt files and double-click.
REM  Skips the first 270 txt files (natural name order: 1,2,9,10).
REM  Appends your sentences to the rest, cycling through them.
REM  Writes a log file. Button "Вернуть всё" restores originals.
REM
REM  Change the default skip count here if needed:
set "SKIP_COUNT=270"
REM ============================================================

chcp 65001 >nul
set "SCRIPT_PATH=%~f0"
set "PS_MARK=TXTAPPEND_PS_BEGIN"

powershell -NoProfile -ExecutionPolicy Bypass -STA -Command "try { $raw = Get-Content -LiteralPath $env:SCRIPT_PATH -Raw -Encoding UTF8; $m = $env:PS_MARK + '_SECTION'; $i = $raw.IndexOf($m); if ($i -lt 0) { throw 'internal marker missing' }; Invoke-Expression $raw.Substring($i + $m.Length); exit $(if ($LASTEXITCODE -ne $null) { $LASTEXITCODE } else { 0 }) } catch { Write-Host $_ -ForegroundColor Red; exit 1 }"

set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo.
    pause
)
endlocal & exit /b %ERR%

TXTAPPEND_PS_BEGIN_SECTION
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
try { [Console]::InputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}
$OutputEncoding = [Console]::OutputEncoding

$script:SkipCount = 270
if ($env:SKIP_COUNT -match '^\d+$') { $script:SkipCount = [int]$env:SKIP_COUNT }

$script:RootDir = Split-Path -Parent $env:SCRIPT_PATH
if ([string]::IsNullOrWhiteSpace($script:RootDir)) { $script:RootDir = (Get-Location).Path }
Set-Location -LiteralPath $script:RootDir

$script:BackupDir = Join-Path $script:RootDir '_txt_backup'
$script:LogSkipPattern = '^_(process|restore)_log_'
$script:GuiMode = $false
$script:StatusLabel = $null

function Get-NaturalKey {
    param([string]$Name)
    $sb = New-Object System.Text.StringBuilder
    $pos = 0
    foreach ($m in [regex]::Matches($Name, '\d+')) {
        if ($m.Index -gt $pos) {
            [void]$sb.Append($Name.Substring($pos, $m.Index - $pos).ToLowerInvariant())
        }
        [void]$sb.Append($m.Value.PadLeft(18, '0'))
        $pos = $m.Index + $m.Length
    }
    if ($pos -lt $Name.Length) { [void]$sb.Append($Name.Substring($pos).ToLowerInvariant()) }
    return $sb.ToString()
}

function Get-TargetTxtFiles {
    param([string]$Dir)
    Get-ChildItem -LiteralPath $Dir -File -Filter '*.txt' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch $script:LogSkipPattern } |
        Sort-Object { Get-NaturalKey $_.Name }, Name
}

function Get-FileStats {
    $files = @(Get-TargetTxtFiles $script:RootDir)
    $total = $files.Count
    $toSkip = [Math]::Min($script:SkipCount, $total)
    $work = 0
    if ($total -gt $toSkip) { $work = $total - $toSkip }
    return @{ Files = $files; Total = $total; ToSkip = $toSkip; Work = $work }
}

function Read-TextPreservingEncoding {
    param([string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $enc = $null
    $offset = 0
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $enc = New-Object System.Text.UTF8Encoding $true
        $offset = 3
    } elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $enc = New-Object System.Text.UnicodeEncoding $false, $true
        $offset = 2
    } elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        $enc = New-Object System.Text.UnicodeEncoding $true, $true
        $offset = 2
    } else {
        $enc = New-Object System.Text.UTF8Encoding $false
        $offset = 0
    }
    $text = $enc.GetString($bytes, $offset, $bytes.Length - $offset)
    return @{ Encoding = $enc; Text = $text }
}

function Add-LastSentence {
    param([string]$Text, [string]$Sentence)
    $hadCrLf = $Text.EndsWith("`r`n")
    $hadLf = (-not $hadCrLf) -and $Text.EndsWith("`n")
    $hadCr = (-not $hadCrLf) -and (-not $hadLf) -and $Text.EndsWith("`r")
    $core = [regex]::Replace($Text, '[\s]+$', '')
    if ([string]::IsNullOrEmpty($core)) { $result = $Sentence }
    else { $result = $core + ' ' + $Sentence }
    if ($hadCrLf) { $result += "`r`n" }
    elseif ($hadLf) { $result += "`n" }
    elseif ($hadCr) { $result += "`r" }
    return $result
}

function Write-Utf8Log {
    param([string]$Path, [string]$Content)
    $utf8bom = New-Object System.Text.UTF8Encoding $true
    [System.IO.File]::WriteAllText($Path, $Content, $utf8bom)
}

function Write-Status {
    param([string]$Message, [string]$Color = 'White')
    if ($null -ne $script:StatusLabel) {
        $script:StatusLabel.Text = $Message
        [System.Windows.Forms.Application]::DoEvents()
    }
    if (-not $script:GuiMode) {
        Write-Host $Message -ForegroundColor $Color
    }
}

function Read-UserLine {
    param([string]$Prompt)
    Write-Host -NoNewline $Prompt
    return [Console]::ReadLine()
}

function Confirm-Yes {
    param([string]$Prompt)
    if ($env:TXT_APPEND_ASSUME_YES -eq '1') { return $true }
    if ($script:GuiMode) {
        $r = [System.Windows.Forms.MessageBox]::Show(
            $Prompt, 'Подтверждение',
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )
        return ($r -eq [System.Windows.Forms.DialogResult]::Yes)
    }
    $a = Read-UserLine ($Prompt + ' [Y/N]: ')
    if ($null -eq $a) { return $false }
    $a = $a.Trim().ToLowerInvariant()
    return ($a -eq 'y' -or $a -eq 'yes' -or $a -eq 'д' -or $a -eq 'да')
}

function Get-SentencesInteractive {
    if (-not [string]::IsNullOrWhiteSpace($env:TXT_APPEND_SENTENCES_FILE) -and (Test-Path -LiteralPath $env:TXT_APPEND_SENTENCES_FILE)) {
        return @(Get-Content -LiteralPath $env:TXT_APPEND_SENTENCES_FILE -Encoding UTF8 |
            ForEach-Object { $_.TrimEnd() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
    if (-not [string]::IsNullOrWhiteSpace($env:TXT_APPEND_SENTENCES)) {
        return @($env:TXT_APPEND_SENTENCES.Split(@('|||'), [StringSplitOptions]::None) |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
    Write-Host ''
    Write-Host 'Введите предложения по одному на строку.' -ForegroundColor Yellow
    Write-Host 'Они будут подставляться по кругу: 1-е, 2-е, 3-е, снова 1-е...'
    Write-Host 'Пустая строка — закончить ввод.'
    Write-Host ''
    $list = New-Object System.Collections.Generic.List[string]
    $n = 1
    while ($true) {
        $line = Read-UserLine ("Предложение {0}: " -f $n)
        if ($null -eq $line) { break }
        if ([string]::IsNullOrWhiteSpace($line)) { break }
        $list.Add($line.Trim())
        $n++
    }
    return @($list)
}

function Invoke-Process {
    param([string[]]$Sentences)

    $stats = Get-FileStats
    $files = @($stats.Files)
    $total = $stats.Total
    $toSkip = $stats.ToSkip
    $work = @()
    if ($total -gt $toSkip) { $work = @($files[$toSkip..($total - 1)]) }

    Write-Status ("Папка: {0}  |  найдено {1}  |  пропуск {2}  |  к обработке {3}" -f $RootDir, $total, $toSkip, $work.Count)

    if ($work.Count -eq 0) {
        Write-Status 'Нечего обрабатывать: txt меньше числа пропуска или файлов нет.' 'Yellow'
        return @{ Ok = 0; Fail = 0; LogPath = $null; Message = 'Нечего обрабатывать: txt меньше числа пропуска или файлов нет.' }
    }

    if ($null -eq $Sentences -or $Sentences.Count -eq 0) {
        $Sentences = @(Get-SentencesInteractive)
    }
    $Sentences = @($Sentences | ForEach-Object { "$_".Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($Sentences.Count -eq 0) {
        Write-Status 'Нужно хотя бы одно предложение.' 'Red'
        return @{ Ok = 0; Fail = 0; LogPath = $null; Message = 'Нужно хотя бы одно предложение.' }
    }

    if (-not (Confirm-Yes ("Начать обработку {0} файлов? Оригиналы сохранятся в _txt_backup" -f $work.Count))) {
        Write-Status 'Отмена.'
        return @{ Ok = 0; Fail = 0; LogPath = $null; Message = 'Отмена.' }
    }

    if (-not (Test-Path -LiteralPath $BackupDir)) {
        New-Item -ItemType Directory -Path $BackupDir | Out-Null
    }

    $stamp = Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'
    $logPath = Join-Path $RootDir ("_process_log_{0}.txt" -f $stamp)
    $log = New-Object System.Text.StringBuilder
    [void]$log.AppendLine("=== Обработка TXT  $stamp ===")
    [void]$log.AppendLine("Папка: $RootDir")
    [void]$log.AppendLine("Всего txt: $total")
    [void]$log.AppendLine("Пропущено первых: $toSkip")
    [void]$log.AppendLine("К обработке: $($work.Count)")
    [void]$log.AppendLine("Предложения ($($Sentences.Count)):")
    for ($i = 0; $i -lt $Sentences.Count; $i++) {
        [void]$log.AppendLine("  $($i + 1). $($Sentences[$i])")
    }
    [void]$log.AppendLine('')
    [void]$log.AppendLine('--- Пропущенные ---')
    for ($i = 0; $i -lt $toSkip; $i++) {
        [void]$log.AppendLine(("[SKIP] {0}" -f $files[$i].Name))
    }
    [void]$log.AppendLine('')
    [void]$log.AppendLine('--- Обработка ---')

    $ok = 0
    $fail = 0
    $idx = 0
    foreach ($f in $work) {
        $sentence = $Sentences[$idx % $Sentences.Count]
        $idx++
        try {
            $bak = Join-Path $BackupDir $f.Name
            if (-not (Test-Path -LiteralPath $bak)) {
                Copy-Item -LiteralPath $f.FullName -Destination $bak -Force
            }
            $read = Read-TextPreservingEncoding $f.FullName
            $newText = Add-LastSentence -Text $read.Text -Sentence $sentence
            [System.IO.File]::WriteAllText($f.FullName, $newText, $read.Encoding)
            $ok++
            [void]$log.AppendLine(("[OK]   {0}  ->  {1}" -f $f.Name, $sentence))
            if (($ok + $fail) % 25 -eq 0 -or ($ok + $fail) -eq $work.Count) {
                Write-Status ("Обработано {0} из {1}..." -f ($ok + $fail), $work.Count)
            }
        } catch {
            $fail++
            [void]$log.AppendLine(("[ERR]  {0}  ->  {1}" -f $f.Name, $_.Exception.Message))
            Write-Status ("Ошибка {0}: {1}" -f $f.Name, $_.Exception.Message) 'Red'
        }
    }

    [void]$log.AppendLine('')
    [void]$log.AppendLine("Итого: успешно $ok, ошибок $fail")
    [void]$log.AppendLine("Бэкап: $BackupDir")
    [void]$log.AppendLine("Лог:   $logPath")
    Write-Utf8Log -Path $logPath -Content $log.ToString()

    $msg = "Готово. Успешно: {0}, ошибок: {1}`r`nЛог: {2}`r`nБэкап: {3}" -f $ok, $fail, $logPath, $BackupDir
    Write-Status $msg 'Green'
    return @{ Ok = $ok; Fail = $fail; LogPath = $logPath; Message = $msg }
}

function Invoke-Restore {
    if (-not (Test-Path -LiteralPath $BackupDir)) {
        $msg = 'Папки бэкапа _txt_backup нет — возвращать нечего.'
        Write-Status $msg 'Yellow'
        return @{ Ok = 0; Fail = 0; LogPath = $null; Message = $msg }
    }
    $backs = @(Get-ChildItem -LiteralPath $BackupDir -File -Filter '*.txt' -ErrorAction SilentlyContinue)
    if ($backs.Count -eq 0) {
        $msg = 'В _txt_backup нет txt-файлов.'
        Write-Status $msg 'Yellow'
        return @{ Ok = 0; Fail = 0; LogPath = $null; Message = $msg }
    }

    if (-not (Confirm-Yes ("Вернуть {0} файл(ов) к оригиналу из _txt_backup?" -f $backs.Count))) {
        Write-Status 'Отмена.'
        return @{ Ok = 0; Fail = 0; LogPath = $null; Message = 'Отмена.' }
    }

    $stamp = Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'
    $logPath = Join-Path $RootDir ("_restore_log_{0}.txt" -f $stamp)
    $log = New-Object System.Text.StringBuilder
    [void]$log.AppendLine("=== Восстановление  $stamp ===")
    [void]$log.AppendLine("Папка: $RootDir")
    [void]$log.AppendLine("Бэкап: $BackupDir")
    [void]$log.AppendLine("Файлов в бэкапе: $($backs.Count)")
    [void]$log.AppendLine('')

    $ok = 0
    $fail = 0
    foreach ($b in $backs) {
        $dest = Join-Path $RootDir $b.Name
        try {
            Copy-Item -LiteralPath $b.FullName -Destination $dest -Force
            $ok++
            [void]$log.AppendLine("[OK]   $($b.Name)")
        } catch {
            $fail++
            [void]$log.AppendLine("[ERR]  $($b.Name)  ->  $($_.Exception.Message)")
        }
    }

    [void]$log.AppendLine('')
    [void]$log.AppendLine("Итого: восстановлено $ok, ошибок $fail")
    [void]$log.AppendLine("Лог: $logPath")
    Write-Utf8Log -Path $logPath -Content $log.ToString()

    $msg = "Готово. Восстановлено: {0}, ошибок: {1}`r`nЛог: {2}" -f $ok, $fail, $logPath
    Write-Status $msg 'Green'
    return @{ Ok = $ok; Fail = $fail; LogPath = $logPath; Message = $msg }
}

function Hide-ConsoleWindow {
    try {
        $code = @"
using System;
using System.Runtime.InteropServices;
public class TxtAppendConsole {
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
        Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue | Out-Null
        $hwnd = [TxtAppendConsole]::GetConsoleWindow()
        if ($hwnd -ne [IntPtr]::Zero) { [TxtAppendConsole]::ShowWindow($hwnd, 0) | Out-Null }
    } catch {}
}

function Show-Gui {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $script:GuiMode = $true
    Hide-ConsoleWindow

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Обработка TXT'
    $form.Size = New-Object System.Drawing.Size(720, 560)
    $form.MinimumSize = New-Object System.Drawing.Size(640, 480)
    $form.StartPosition = 'CenterScreen'
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 10)

    $lblFolder = New-Object System.Windows.Forms.Label
    $lblFolder.Location = New-Object System.Drawing.Point(16, 14)
    $lblFolder.AutoSize = $false
    $lblFolder.Size = New-Object System.Drawing.Size(670, 22)
    $lblFolder.Anchor = 'Top,Left,Right'
    $lblFolder.Text = "Папка: $RootDir"

    $lblSkip = New-Object System.Windows.Forms.Label
    $lblSkip.Location = New-Object System.Drawing.Point(16, 44)
    $lblSkip.AutoSize = $true
    $lblSkip.Text = 'Пропустить первых файлов:'

    $numSkip = New-Object System.Windows.Forms.NumericUpDown
    $numSkip.Location = New-Object System.Drawing.Point(250, 40)
    $numSkip.Size = New-Object System.Drawing.Size(90, 26)
    $numSkip.Minimum = 0
    $numSkip.Maximum = 10000000
    $numSkip.Value = $SkipCount

    $lblStats = New-Object System.Windows.Forms.Label
    $lblStats.Location = New-Object System.Drawing.Point(16, 74)
    $lblStats.AutoSize = $false
    $lblStats.Size = New-Object System.Drawing.Size(670, 22)
    $lblStats.Anchor = 'Top,Left,Right'

    $script:SkipBox = $numSkip
    $script:StatsLabel = $lblStats
    $script:SentBox = $box
    $updateStats = {
        $script:SkipCount = [int]$script:SkipBox.Value
        $s = Get-FileStats
        $script:StatsLabel.Text = "Найдено TXT: $($s.Total)    пропуск: $($s.ToSkip)    будет обработано: $($s.Work)"
    }
    $numSkip.Add_ValueChanged($updateStats)
    & $updateStats

    $lblSent = New-Object System.Windows.Forms.Label
    $lblSent.Location = New-Object System.Drawing.Point(16, 106)
    $lblSent.AutoSize = $false
    $lblSent.Size = New-Object System.Drawing.Size(670, 40)
    $lblSent.Anchor = 'Top,Left,Right'
    $lblSent.Text = "Предложения — по одному на строку.`r`nК каждому txt после пропуска допишется следующее по кругу."

    $box = New-Object System.Windows.Forms.TextBox
    $box.Multiline = $true
    $box.ScrollBars = 'Vertical'
    $box.Location = New-Object System.Drawing.Point(16, 150)
    $box.Size = New-Object System.Drawing.Size(670, 230)
    $box.Anchor = 'Top,Bottom,Left,Right'
    $box.AcceptsReturn = $true
    $box.Font = New-Object System.Drawing.Font('Segoe UI', 11)

    $btnGo = New-Object System.Windows.Forms.Button
    $btnGo.Text = 'Обработать файлы'
    $btnGo.Location = New-Object System.Drawing.Point(16, 396)
    $btnGo.Size = New-Object System.Drawing.Size(250, 42)
    $btnGo.Anchor = 'Bottom,Left'
    $btnGo.BackColor = [System.Drawing.Color]::FromArgb(46, 125, 50)
    $btnGo.ForeColor = [System.Drawing.Color]::White
    $btnGo.FlatStyle = 'Flat'

    $btnRestore = New-Object System.Windows.Forms.Button
    $btnRestore.Text = 'Вернуть всё как было'
    $btnRestore.Location = New-Object System.Drawing.Point(280, 396)
    $btnRestore.Size = New-Object System.Drawing.Size(250, 42)
    $btnRestore.Anchor = 'Bottom,Left'
    $btnRestore.BackColor = [System.Drawing.Color]::FromArgb(198, 40, 40)
    $btnRestore.ForeColor = [System.Drawing.Color]::White
    $btnRestore.FlatStyle = 'Flat'

    $script:StatusLabel = New-Object System.Windows.Forms.Label
    $script:StatusLabel.Location = New-Object System.Drawing.Point(16, 450)
    $script:StatusLabel.AutoSize = $false
    $script:StatusLabel.Size = New-Object System.Drawing.Size(670, 50)
    $script:StatusLabel.Anchor = 'Bottom,Left,Right'
    $script:StatusLabel.Text = 'Лог появится в этой же папке после обработки.'

    $script:BtnGo = $btnGo
    $script:BtnRestore = $btnRestore
    $btnGo.Add_Click({
        $script:SkipCount = [int]$script:SkipBox.Value
        $sentences = @($script:SentBox.Lines | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
        $script:BtnGo.Enabled = $false
        $script:BtnRestore.Enabled = $false
        try {
            $res = Invoke-Process -Sentences $sentences
            [System.Windows.Forms.MessageBox]::Show($res.Message, 'Обработка', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
            $script:SkipCount = [int]$script:SkipBox.Value
            $s = Get-FileStats
            $script:StatsLabel.Text = "Найдено TXT: $($s.Total)    пропуск: $($s.ToSkip)    будет обработано: $($s.Work)"
        } catch {
            [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Ошибка', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        } finally {
            $script:BtnGo.Enabled = $true
            $script:BtnRestore.Enabled = $true
        }
    })

    $btnRestore.Add_Click({
        $script:BtnGo.Enabled = $false
        $script:BtnRestore.Enabled = $false
        try {
            $res = Invoke-Restore
            [System.Windows.Forms.MessageBox]::Show($res.Message, 'Восстановление', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        } catch {
            [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Ошибка', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        } finally {
            $script:BtnGo.Enabled = $true
            $script:BtnRestore.Enabled = $true
        }
    })

    $form.Controls.AddRange(@($lblFolder, $lblSkip, $numSkip, $lblStats, $lblSent, $box, $btnGo, $btnRestore, $script:StatusLabel))
    $form.Add_Shown({ $script:SentBox.Focus() })
    [void]$form.ShowDialog()
}

function Show-ConsoleMenu {
    Write-Host ''
    Write-Host '========================================' -ForegroundColor Cyan
    Write-Host '  Обработка TXT-файлов' -ForegroundColor Cyan
    Write-Host '========================================' -ForegroundColor Cyan
    Write-Host ("  Папка: {0}" -f $RootDir)
    Write-Host ("  Пропуск первых: {0} шт." -f $SkipCount)
    Write-Host '----------------------------------------'
    Write-Host '  1. Обработать (дописать предложения)'
    Write-Host '  2. Вернуть всё как было'
    Write-Host '  3. Выход'
    Write-Host '========================================'
}

$action = $env:TXT_APPEND_ACTION
if ([string]::IsNullOrWhiteSpace($action)) { $action = 'gui' }
$action = $action.Trim().ToLowerInvariant()

if ($action -eq 'process') {
    Invoke-Process | Out-Null
    exit 0
}
if ($action -eq 'restore') {
    Invoke-Restore | Out-Null
    exit 0
}
if ($action -eq 'menu') {
    $running = $true
    while ($running) {
        Show-ConsoleMenu
        $choice = Read-UserLine 'Выбор: '
        if ($null -eq $choice) { break }
        switch -Regex ($choice.Trim()) {
            '^1$' { Invoke-Process | Out-Null }
            '^2$' { Invoke-Restore | Out-Null }
            '^(3|q)$' { $running = $false }
            default { Write-Host 'Введите 1, 2 или 3.' -ForegroundColor Yellow }
        }
    }
    exit 0
}

try {
    Show-Gui
    exit 0
} catch {
    Write-Host "Окно не открылось: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Запускаю текстовое меню.'
    $env:TXT_APPEND_ACTION = 'menu'
    $script:GuiMode = $false
    $running = $true
    while ($running) {
        Show-ConsoleMenu
        $choice = Read-UserLine 'Выбор: '
        if ($null -eq $choice) { break }
        switch -Regex ($choice.Trim()) {
            '^1$' { Invoke-Process | Out-Null }
            '^2$' { Invoke-Restore | Out-Null }
            '^(3|q)$' { $running = $false }
            default { Write-Host 'Введите 1, 2 или 3.' -ForegroundColor Yellow }
        }
    }
    exit 0
}
