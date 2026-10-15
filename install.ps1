<#
.SYNOPSIS
  Installs Delta into a local virtual environment (.venv) next to this script.
.DESCRIPTION
  Run from PowerShell:   powershell -ExecutionPolicy Bypass -File .\install.ps1
  Options:
    -Voice          also install optional voice packages (offline speech-to-text, text-to-speech)
    -Ocr            also install the OCR Python package (you still need the Tesseract program)
    -StartOnLogin   start Delta automatically when you sign in to Windows
#>
[CmdletBinding()]
param(
    [switch]$Voice,
    [switch]$Ocr,
    [switch]$StartOnLogin
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

Write-Host ''
Write-Host '== Delta installer ==' -ForegroundColor Cyan

# 1) Find Python 3.10 or newer (the Microsoft Store "python" stub is skipped because it exits with an error)
$candidates = @(
    @{ Exe = 'py';      Args = @('-3') },
    @{ Exe = 'python';  Args = @() },
    @{ Exe = 'python3'; Args = @() }
)
$py = $null
foreach ($c in $candidates) {
    if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
        $ver = & $c.Exe @($c.Args) -c "import sys; print(str(sys.version_info[0]) + '.' + str(sys.version_info[1]))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver -and ([version]$ver -ge [version]'3.10')) {
            $py = $c
            Write-Host ("Found Python " + $ver + " via '" + $c.Exe + "'") -ForegroundColor Green
            break
        }
    }
}
if (-not $py) {
    Write-Host 'Python 3.10 or newer was not found.' -ForegroundColor Red
    Write-Host '  1. Download it from https://www.python.org/downloads/windows/'
    Write-Host '  2. In the installer, TICK "Add python.exe to PATH", then click Install Now.'
    Write-Host '  3. Close this window, open a new one and run this script again.'
    exit 1
}

# 2) Virtual environment
$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host 'Creating virtual environment (.venv) ...'
    & $py.Exe @($py.Args) -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host 'Could not create the virtual environment.' -ForegroundColor Red; exit 1 }
}

# 3) Packages
Write-Host 'Installing packages (this can take a few minutes) ...'
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host 'Package installation failed. See the messages above.' -ForegroundColor Red; exit 1 }

if ($Voice) {
    Write-Host 'Installing voice packages ...'
    & $venvPy -m pip install faster-whisper sounddevice numpy pyttsx3 SpeechRecognition
}
if ($Ocr) {
    Write-Host 'Installing OCR package ...'
    & $venvPy -m pip install pytesseract
    Write-Host 'Note: OCR also needs the Tesseract program: https://github.com/UB-Mannheim/tesseract/wiki' -ForegroundColor Yellow
}

# 4) Config files (never overwrites yours)
if (-not (Test-Path 'config.yaml'))   { Copy-Item 'config.example.yaml'   'config.yaml';   Write-Host 'Created config.yaml' }
if (-not (Test-Path 'routines.yaml')) { Copy-Item 'routines.example.yaml' 'routines.yaml'; Write-Host 'Created routines.yaml' }

# 5) Optional: start on login
if ($StartOnLogin) {
    & (Join-Path $PSScriptRoot 'scripts\startup.ps1') -Enable
}

# 6) Health check
Write-Host ''
& $venvPy -m delta doctor

Write-Host ''
Write-Host 'Done. Start Delta by double-clicking run.bat' -ForegroundColor Green
Write-Host 'Then run the one-time hardware check:  .venv\Scripts\python.exe -m delta selftest'
