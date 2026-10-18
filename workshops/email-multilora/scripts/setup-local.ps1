[CmdletBinding()]
param(
    [ValidateSet('cpu', 'cuda')]
    [string]$Device = 'cpu',
    [string]$Python = 'python',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$workshop = Split-Path -Parent $PSScriptRoot
Push-Location $workshop
try {
    function Invoke-Checked {
        param([string]$Executable, [string[]]$Arguments)
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed (exit $LASTEXITCODE): $Executable $($Arguments -join ' ')"
        }
    }

    $venvPython = '.\.venv\Scripts\python.exe'
    if (!$CheckOnly) {
        if (!(Test-Path -LiteralPath '.venv')) {
            Invoke-Checked $Python @('-c', 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 14), "Python 3.11-3.13 required"')
            Invoke-Checked $Python @('-m', 'venv', '.venv')
        }
        if (!(Test-Path -LiteralPath $venvPython)) {
            throw 'Existing .venv is incomplete. Inspect it and recreate it explicitly; setup will not delete it.'
        }
        Invoke-Checked $venvPython @('-c', 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 14), "Python 3.11-3.13 required"')
        $build = if ($Device -eq 'cuda') { 'cu128' } else { 'cpu' }
        Invoke-Checked $venvPython @('-m', 'pip', 'install', "torch==2.10.0+$build", '--index-url', "https://download.pytorch.org/whl/$build")
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '-e', '.[training,dev]')
        Invoke-Checked $venvPython @('-m', 'ipykernel', 'install', '--sys-prefix', '--name', 'email-multilora', '--display-name', 'Python (email-multilora)')
    }
    if (!(Test-Path -LiteralPath $venvPython)) {
        throw 'Workshop .venv is missing. Run setup without -CheckOnly first.'
    }
    Invoke-Checked $venvPython @('-m', 'pip', 'check')
    Invoke-Checked $venvPython @('scripts\check_local.py', '--device', $Device)
}
finally {
    Pop-Location
}
