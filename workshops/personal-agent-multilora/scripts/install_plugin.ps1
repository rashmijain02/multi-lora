# Link the PersonaDesk plugin into the Hermes plugin directory (Windows).
# Usage (from the repository root): .\workshops\personal-agent-multilora\scripts\install_plugin.ps1
# A directory junction needs no administrator rights; the plugin resolves the workshop root
# through it at runtime.
$ErrorActionPreference = 'Stop'

$source = (Resolve-Path (Join-Path $PSScriptRoot '..\hermes_plugin')).Path
$hermesHome = if ($env:HERMES_HOME) {
    $env:HERMES_HOME
} elseif (Get-Command hermes -ErrorAction SilentlyContinue) {
    Split-Path -Parent (hermes config path)   # %LOCALAPPDATA%\hermes on native Windows
} else {
    Join-Path $env:LOCALAPPDATA 'hermes'
}
$plugins = Join-Path $hermesHome 'plugins'
$target = Join-Path $plugins 'personadesk'

New-Item -ItemType Directory -Force -Path $plugins | Out-Null
if (Test-Path $target) {
    $item = Get-Item $target -Force
    if (-not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to replace non-link $target; remove it yourself first."
    }
    $item.Delete()
}
New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Host "Linked personadesk plugin -> $target"
Write-Host 'Each Hermes profile discovers plugins only in its own home. For the persona profiles,'
Write-Host 'run scripts/setup_hermes.py, which links the plugin into each profile, or set'
Write-Host 'HERMES_HOME to a profile directory before running this script.'
