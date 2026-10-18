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
    throw "Status environment file not found: $resolvedEnvFile"
}

$values = @{}
foreach ($line in Get-Content -LiteralPath $resolvedEnvFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
    }
}
foreach ($name in @('AZURE_SUBSCRIPTION_ID', 'FOUNDRY_RESOURCE_GROUP', 'FOUNDRY_ACCOUNT_NAME')) {
    if (-not $values.ContainsKey($name) -or [string]::IsNullOrWhiteSpace([string]$values[$name])) {
        throw "Missing $name in $resolvedEnvFile."
    }
}

$az = Get-Command az -ErrorAction SilentlyContinue
if (-not $az) {
    $candidate = Join-Path $env:ProgramFiles 'Microsoft SDKs\Azure\CLI2\wbin\az.cmd'
    if (-not (Test-Path -LiteralPath $candidate)) { throw 'Azure CLI was not found.' }
    $azCommand = $candidate
} else {
    $azCommand = $az.Source
}

$accountId = & $azCommand cognitiveservices account show `
    --subscription $values['AZURE_SUBSCRIPTION_ID'] `
    --resource-group $values['FOUNDRY_RESOURCE_GROUP'] `
    --name $values['FOUNDRY_ACCOUNT_NAME'] `
    --query id --output tsv --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'Unable to read the configured Foundry account.' }

$url = "https://management.azure.com$accountId/managedComputeDeployments?api-version=2026-07-15-preview"
$json = & $azCommand rest --method get --url $url --output json --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'Unable to list managed-compute deployments.' }
$payload = ConvertFrom-Json -InputObject ($json -join [Environment]::NewLine)
$deployments = @($payload.value)
if ($deployments.Count -eq 0) {
    Write-Host 'No managed-compute deployments exist in the configured Foundry account.' -ForegroundColor Yellow
    $armState = & $azCommand deployment group show `
        --subscription $values['AZURE_SUBSCRIPTION_ID'] `
        --resource-group $values['FOUNDRY_RESOURCE_GROUP'] `
        --name 'email-workshop-foundry' `
        --query properties.provisioningState --output tsv --only-show-errors 2>$null
    if ($LASTEXITCODE -eq 0 -and $armState) {
        Write-Host "Latest workshop ARM deployment state: $armState"
    }
    return
}

$deployments |
    ForEach-Object {
        [pscustomobject]@{
            Name = $_.name
            State = $_.properties.provisioningState
            SKU = $_.sku.name
            Capacity = $_.sku.capacity
            Accelerator = $_.properties.acceleratorType
            Model = ([string]$_.properties.model -replace '^.*/models/', '' -replace '/versions/', ' v')
        }
    } |
    Format-Table -AutoSize
