[CmdletBinding()]
param(
    [ValidateSet('Probe', 'ShowProposal', 'ListModels', 'Deploy')]
    [string]$Action = 'Probe',

    [string]$EnvFile = '..\..\.env',

    [string]$ModelNameFilter = 'nvidia',

    [string]$ModelAssetName,

    [string]$ModelVersion,

    [switch]$Apply,

    [switch]$InstallMlExtension
)

$ErrorActionPreference = 'Stop'
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8Encoding
[Console]::OutputEncoding = $utf8Encoding
$OutputEncoding = $utf8Encoding
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

function Resolve-OptionalPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,

        [Parameter(Mandatory = $true)]
        [string]$CandidatePath
    )

    if ([System.IO.Path]::IsPathRooted($CandidatePath)) {
        return [System.IO.Path]::GetFullPath($CandidatePath)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $CandidatePath))
}

function Get-WorkshopPaths {
    $scriptPath = Split-Path -Parent $PSCommandPath
    $workshopRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptPath '..'))
    $proposalPath = Join-Path $workshopRoot '.env.foundry.proposal'
    $envPath = Resolve-OptionalPath -BasePath $workshopRoot -CandidatePath $EnvFile
    return @{
        ScriptPath = $scriptPath
        WorkshopRoot = $workshopRoot
        ProposalPath = $proposalPath
        EnvPath = $envPath
    }
}

function Get-PythonRunner {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkshopRoot
    )

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        return @($uv.Source, 'run', '--extra', 'cloud', '--extra', 'dev', 'python', '-m')
    }

    $venvPython = Join-Path $WorkshopRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        return @($venvPython, '-m')
    }

    throw 'Neither uv nor workshops/email-multilora/.venv/Scripts/python.exe is available.'
}

function Invoke-PythonModule {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkshopRoot,

        [Parameter(Mandatory = $true)]
        [string]$Module,

        [Parameter()]
        [string[]]$Arguments = @()
    )

    $runner = Get-PythonRunner -WorkshopRoot $WorkshopRoot
    & $runner[0] $runner[1..($runner.Length - 1)] $Module @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Module $Module failed with exit code $LASTEXITCODE."
    }
}

function Ensure-AzCli {
    $az = Get-Command az -ErrorAction SilentlyContinue
    if (-not $az) {
        throw 'Azure CLI is required for this action. Install az and run az login first.'
    }
    return $az.Source
}

function Ensure-AzMlExtension {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AzCommand
    )

    $null = & $AzCommand extension show --name ml --only-show-errors 2>$null
    if ($LASTEXITCODE -eq 0) {
        return
    }
    if (-not $InstallMlExtension) {
        throw 'Azure CLI extension "ml" is required for ListModels. Re-run with -InstallMlExtension to install it.'
    }
    & $AzCommand extension add --name ml --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to install Azure CLI extension "ml".'
    }
}

function Show-ProposalFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProposalPath
    )

    if (-not (Test-Path $ProposalPath)) {
        throw "Proposal file not found: $ProposalPath"
    }
    Get-Content $ProposalPath
}

$paths = Get-WorkshopPaths

Push-Location $paths.WorkshopRoot
try {
    switch ($Action) {
        'Probe' {
            $args = @('email_workshop.foundry_probe', '--env-file', $paths.EnvPath)
            Invoke-PythonModule -WorkshopRoot $paths.WorkshopRoot -Module $args[0] -Arguments $args[1..($args.Length - 1)]
            Write-Host ''
            Write-Host 'Generated proposal file:'
            Write-Host $paths.ProposalPath
        }
        'ShowProposal' {
            Show-ProposalFile -ProposalPath $paths.ProposalPath
        }
        'ListModels' {
            $az = Ensure-AzCli
            Ensure-AzMlExtension -AzCommand $az
            $modelJson = & $az ml model list --registry-name azure-huggingface --max-results 1000 --output json
            if ($LASTEXITCODE -ne 0) {
                throw 'az ml model list failed.'
            }
            $modelText = $modelJson -join [Environment]::NewLine
            $modelAssets = @()
            if ($modelText.Trim()) {
                $modelResponse = ConvertFrom-Json -InputObject $modelText
                $modelAssets = @($modelResponse)
            }
            try {
                $namePattern = [regex]::new($ModelNameFilter, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
            } catch [System.ArgumentException] {
                throw "Invalid model-name regex '$ModelNameFilter': $($_.Exception.Message)"
            }
            $matchingModels = @(
                $modelAssets |
                    Where-Object {
                        $_.name -and $namePattern.IsMatch([string]$_.name)
                    } |
                    Sort-Object name
            )
            if ($matchingModels.Count -eq 0) {
                Write-Host "No models matched '$ModelNameFilter'."
                return
            }
            $matchingModels |
                Select-Object name, @{ Name = 'latest_version'; Expression = { $_.'latest version' } } |
                Format-Table -AutoSize
            if ($ModelAssetName -and $ModelVersion) {
                Write-Host ''
                Write-Host 'Suggested FOUNDRY_MODEL_ID:'
                Write-Host "azureml://registries/azure-huggingface/models/$ModelAssetName/versions/$ModelVersion"
            }
        }
        'Deploy' {
            $args = @('email_workshop.foundry_deploy', '--env-file', $paths.EnvPath)
            if ($Apply) {
                $args += '--apply'
            }
            Invoke-PythonModule -WorkshopRoot $paths.WorkshopRoot -Module $args[0] -Arguments $args[1..($args.Length - 1)]
        }
    }
}
finally {
    Pop-Location
}