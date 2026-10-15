<#
.SYNOPSIS
  Start Delta automatically when you sign in (a shortcut in your Startup folder; no admin rights needed).
  Enable:   powershell -ExecutionPolicy Bypass -File scripts\startup.ps1 -Enable
  Disable:  powershell -ExecutionPolicy Bypass -File scripts\startup.ps1 -Disable
.NOTES
  Delta then runs in the background without a window. Open its page any time from
  Start menu > "Delta (open)", which opens the current secret-token link in your browser.
#>
[CmdletBinding()]
param([switch]$Enable, [switch]$Disable)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $PSScriptRoot
$startup = [Environment]::GetFolderPath('Startup')
$programs = [Environment]::GetFolderPath('Programs')
$lnkStart = Join-Path $startup  'Delta.lnk'
$lnkOpen  = Join-Path $programs 'Delta (open).lnk'

if ($Disable) {
    Remove-Item $lnkStart -ErrorAction SilentlyContinue
    Remove-Item $lnkOpen  -ErrorAction SilentlyContinue
    Write-Host 'Delta will no longer start on login.'
    return
}
if (-not $Enable) { Write-Host 'Use -Enable or -Disable.'; return }

$pyw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pyw)) { throw 'Run install.ps1 first (.venv not found).' }

$ws = New-Object -ComObject WScript.Shell

$s = $ws.CreateShortcut($lnkStart)
$s.TargetPath = $pyw
$s.Arguments = '-m delta serve --no-browser'
$s.WorkingDirectory = $root
$s.WindowStyle = 7
$s.Description = 'Delta assistant (background)'
$s.Save()

$o = $ws.CreateShortcut($lnkOpen)
$o.TargetPath = $pyw
$o.Arguments = '-m delta open'
$o.WorkingDirectory = $root
$o.WindowStyle = 7
$o.Description = 'Open the Delta page in your browser'
$o.Save()

Write-Host 'Delta will start in the background when you sign in.'
Write-Host 'Open it from the Start menu: "Delta (open)".'
