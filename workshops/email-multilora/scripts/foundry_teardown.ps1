[CmdletBinding()]
param(
    [string]$EnvFile = '.env.foundry.proposal'
)

$ErrorActionPreference = 'Stop'
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8Encoding
[Console]::OutputEncoding = $utf8Encoding
$OutputEncoding = $utf8Encoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$scriptDirectory = Split-Path -Parent $PSCommandPath
$workshopRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDirectory '..'))
$resolvedEnvFile = if ([System.IO.Path]::IsPathRooted($EnvFile)) {
    [System.IO.Path]::GetFullPath($EnvFile)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $workshopRoot $EnvFile))
}
if (-not (Test-Path -LiteralPath $resolvedEnvFile)) {
    throw "Teardown environment file not found: $resolvedEnvFile"
}

$values = @{}
foreach ($line in Get-Content -LiteralPath $resolvedEnvFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        $key = $Matches[1]
        $value = $Matches[2].Trim()
        if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[-1] -eq '"') -or ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
}

$requiredNames = @(
    'AZURE_SUBSCRIPTION_ID',
    'FOUNDRY_RESOURCE_GROUP',
    'FOUNDRY_ACCOUNT_NAME',
    'FOUNDRY_DEPLOYMENT_NAME'
)
foreach ($name in $requiredNames) {
    if (-not $values.ContainsKey($name) -or [string]::IsNullOrWhiteSpace([string]$values[$name]) -or [string]$values[$name] -match 'REPLACE_ME') {
        throw "Missing valid $name in $resolvedEnvFile. Refusing teardown."
    }
}

$deploymentName = [string]$values['FOUNDRY_DEPLOYMENT_NAME']
Write-Host 'Teardown target:' -ForegroundColor Yellow
Write-Host "  Existing Foundry account: $($values['FOUNDRY_ACCOUNT_NAME'])"
Write-Host "  Managed-compute deployment: $deploymentName"
Write-Host '  Preserved: Foundry account, project, resource group, and unrelated deployments'
Write-Host 'Deleting the managed-compute deployment releases its accelerator allocation and stops its billing after Azure confirms deletion.' -ForegroundColor Yellow
Write-Host 'This does not erase charges already incurred.' -ForegroundColor Yellow
Write-Host ''
$confirmation = Read-Host "Type DELETE $deploymentName to confirm"
if ($confirmation -cne "DELETE $deploymentName") {
    Write-Host 'Teardown cancelled. No Azure resources were changed.' -ForegroundColor Green
    return
}

$forwardedNames = @(
    'AZURE_SUBSCRIPTION_ID',
    'FOUNDRY_RESOURCE_GROUP',
    'FOUNDRY_LOCATION',
    'FOUNDRY_ACCOUNT_NAME',
    'FOUNDRY_PROJECT_NAME',
    'FOUNDRY_DEPLOYMENT_NAME',
    'FOUNDRY_MODEL_ID',
    'FOUNDRY_DEPLOYMENT_TEMPLATE_ID',
    'FOUNDRY_ACCELERATOR_TYPE',
    'FOUNDRY_CAPACITY'
)
$previousValues = @{}
foreach ($name in $forwardedNames) {
    $previousValues[$name] = [Environment]::GetEnvironmentVariable($name)
    if ($values.ContainsKey($name)) {
        [Environment]::SetEnvironmentVariable($name, [string]$values[$name], 'Process')
    }
}
$previousValues['FOUNDRY_TEARDOWN_APPROVED'] = [Environment]::GetEnvironmentVariable('FOUNDRY_TEARDOWN_APPROVED')
[Environment]::SetEnvironmentVariable('FOUNDRY_TEARDOWN_APPROVED', 'true', 'Process')
try {
    Push-Location $workshopRoot
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        & $uv.Source run --extra cloud --extra dev python -m email_workshop.foundry_deploy --env-file $resolvedEnvFile --delete
    } else {
        $python = Join-Path $workshopRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $python)) {
            throw 'Install uv or create the workshop .venv before running teardown.'
        }
        & $python -m email_workshop.foundry_deploy --env-file $resolvedEnvFile --delete
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Foundry teardown failed with exit code $LASTEXITCODE. Verify deployment state privately in Azure Portal."
    }
} finally {
    Pop-Location
    foreach ($name in $previousValues.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousValues[$name], 'Process')
    }
}
