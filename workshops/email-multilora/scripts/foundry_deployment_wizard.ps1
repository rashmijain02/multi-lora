[CmdletBinding()]
param(
    [string]$EnvFile = '..\..\.env',
    [string]$ModelFilter = 'nvidia'
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
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $workshopRoot '..\..'))
$proposalPath = Join-Path $workshopRoot '.env.foundry.proposal'

function Resolve-InputPath {
    param([string]$Path, [string]$BasePath)
    if ([System.IO.Path]::IsPathRooted($Path)) { return [System.IO.Path]::GetFullPath($Path) }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Add-DotEnvValues {
    param([string]$Path, [hashtable]$Values)
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $key = $Matches[1]
            if (-not $Values.ContainsKey($key)) {
                $value = $Matches[2].Trim()
                if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[-1] -eq '"') -or ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
                $Values[$key] = $value
            }
        }
    }
}

function Get-EnvValue {
    param([hashtable]$Values, [string]$Name, [string]$Fallback = '')
    if ($Values.ContainsKey($Name) -and $Values[$Name] -and $Values[$Name] -notmatch 'REPLACE_ME') {
        return [string]$Values[$Name]
    }
    return $Fallback
}

function Invoke-AzJson {
    param([string[]]$Arguments)
    $output = & $script:azCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI command failed: az $($Arguments[0..([Math]::Min(2, $Arguments.Length - 1))] -join ' ') (exit $LASTEXITCODE). Check sign-in, subscription access, and permissions."
    }
    $jsonText = $output -join [Environment]::NewLine
    if (-not $jsonText.Trim()) { return $null }
    return ConvertFrom-Json -InputObject $jsonText
}

function Select-NumberedItem {
    param([object[]]$Items, [string]$Prompt)
    while ($true) {
        $answer = Read-Host $Prompt
        $number = 0
        if ([int]::TryParse($answer, [ref]$number) -and $number -ge 1 -and $number -le $Items.Count) {
            return $Items[$number - 1]
        }
        Write-Host "Enter a number from 1 to $($Items.Count)." -ForegroundColor Yellow
    }
}

function Ensure-AzureCli {
    if (Get-Command az -ErrorAction SilentlyContinue) {
        $script:azCommand = (Get-Command az).Source
        return
    }
    $defaultAzDirectory = Join-Path $env:ProgramFiles 'Microsoft SDKs\Azure\CLI2\wbin'
    $azCmdPath = Join-Path $defaultAzDirectory 'az.cmd'
    if (Test-Path $azCmdPath) {
        $env:Path = "$defaultAzDirectory;$env:Path"
        $script:azCommand = $azCmdPath
        return
    }
    throw 'Azure CLI was not found. Install Microsoft Azure CLI, open a new PowerShell session, and rerun this wizard.'
}

function Ensure-Login {
    & $script:azCommand account show --subscription $script:subscription --output none 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'No active Azure CLI session for the configured subscription; starting az login.' -ForegroundColor Cyan
        & $script:azCommand login --output none
        if ($LASTEXITCODE -ne 0) { throw 'az login did not complete successfully.' }
        & $script:azCommand account show --subscription $script:subscription --output none
        if ($LASTEXITCODE -ne 0) { throw 'The signed-in identity cannot access the subscription from the configured .env.' }
    }
}

function Ensure-MlExtension {
    & $script:azCommand extension show --name ml --output none 2>$null
    if ($LASTEXITCODE -eq 0) { return }
    Write-Host 'The Azure CLI ml extension is needed to list model assets in the azure-huggingface registry.' -ForegroundColor Cyan
    $answer = Read-Host 'Install the stable Azure CLI ml extension now? [y/N]'
    if ($answer -notmatch '^(y|yes)$') { throw 'Cannot enumerate model choices without the ml extension. No extension was installed.' }
    & $script:azCommand extension add --name ml
    if ($LASTEXITCODE -ne 0) { throw 'Azure CLI ml extension installation failed.' }
}

function Read-ModelNames {
    param([string]$Filter)
    $filterLabel = if ($Filter) { $Filter } else { 'all model names' }
    $namePattern = $null
    if ($Filter) {
        try {
            $namePattern = [regex]::new($Filter, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        } catch [System.ArgumentException] {
            throw "Invalid model-name regex '$Filter': $($_.Exception.Message)"
        }
    }
    Write-Host "Querying registry model assets through az ml (filter: $filterLabel)..." -ForegroundColor Cyan
    $response = Invoke-AzJson -Arguments @('ml', 'model', 'list', '--registry-name', 'azure-huggingface', '--max-results', '1000', '--output', 'json')
    $assets = @($response)
    $matching = @(
        $assets |
            Where-Object {
                $_.name -and (-not $namePattern -or $namePattern.IsMatch([string]$_.name))
            } |
            Sort-Object name
    )
    Write-Host "Matched $($matching.Count) of $($assets.Count) registry model names."
    return $matching
}

function Read-ModelVersions {
    param([string]$Name)
    Write-Host "Querying published versions for '$Name'..." -ForegroundColor Cyan
    $response = Invoke-AzJson -Arguments @('ml', 'model', 'list', '--registry-name', 'azure-huggingface', '--name', $Name, '--output', 'json')
    $versions = @(
        @($response) |
            Where-Object { $_.name -eq $Name -and -not [string]::IsNullOrWhiteSpace([string]$_.version) } |
            Sort-Object version -Descending
    )
    if ($versions.Count -eq 0) {
        throw "Registry returned no versioned assets for '$Name'."
    }
    return $versions
}

function Get-TemplateDetails {
    param([string]$TemplateUri)
    $match = [regex]::Match(
        $TemplateUri.Trim(),
        '^azureml://registries/azure-huggingface/deploymenttemplates/(?<name>[^/\s]+)/versions/(?<version>[^/\s]+)$',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    if (-not $match.Success) { return $null }
    return Invoke-AzJson -Arguments @(
        'ml', 'deployment-template', 'show',
        '--registry-name', 'azure-huggingface',
        '--name', $match.Groups['name'].Value,
        '--version', $match.Groups['version'].Value,
        '--output', 'json'
    )
}

function Get-ExistingDeploymentMatches {
    param([string]$AccountResourceId, [string]$ModelUri)
    $uri = "https://management.azure.com$AccountResourceId/managedComputeDeployments?api-version=2026-07-15-preview"
    try {
        $payload = Invoke-AzJson -Arguments @('rest', '--method', 'get', '--uri', $uri, '--output', 'json')
        return @($payload.value | Where-Object { $_.properties.model -eq $ModelUri -and $_.properties.deploymentTemplate -and $_.properties.acceleratorType })
    } catch {
        Write-Host 'Could not read existing deployment templates; enter a template from the Foundry model Deploy details.' -ForegroundColor Yellow
        return @()
    }
}

$values = @{}
$knownEnvironmentNames = @(
    'AZURE_SUBSCRIPTION_ID', 'AZURE_RESOURCE_GROUP', 'AZURE_LOCATION', 'AZURE_AI_ACCOUNT_NAME',
    'AZURE_AI_PROJECT_NAME', 'AZURE_AI_PROJECT_ENDPOINT', 'FOUNDRY_RESOURCE_GROUP',
    'FOUNDRY_LOCATION', 'FOUNDRY_ACCOUNT_NAME', 'FOUNDRY_PROJECT_NAME', 'FOUNDRY_DEPLOYMENT_NAME',
    'FOUNDRY_MODEL_ID', 'FOUNDRY_DEPLOYMENT_TEMPLATE_ID', 'FOUNDRY_ACCELERATOR_TYPE', 'FOUNDRY_CAPACITY'
)
foreach ($name in $knownEnvironmentNames) {
    $current = [Environment]::GetEnvironmentVariable($name)
    if ($current) { $values[$name] = $current }
}
$resolvedEnvFile = Resolve-InputPath -Path $EnvFile -BasePath $workshopRoot
Add-DotEnvValues -Path (Join-Path $repositoryRoot '.env') -Values $values
Add-DotEnvValues -Path (Join-Path $workshopRoot '.env') -Values $values
Add-DotEnvValues -Path $resolvedEnvFile -Values $values
Add-DotEnvValues -Path (Join-Path $workshopRoot '.env.foundry') -Values $values

$script:subscription = Get-EnvValue -Values $values -Name 'AZURE_SUBSCRIPTION_ID'
$resourceGroup = Get-EnvValue -Values $values -Name 'FOUNDRY_RESOURCE_GROUP' -Fallback (Get-EnvValue -Values $values -Name 'AZURE_RESOURCE_GROUP')
$location = Get-EnvValue -Values $values -Name 'FOUNDRY_LOCATION' -Fallback (Get-EnvValue -Values $values -Name 'AZURE_LOCATION')
$accountName = Get-EnvValue -Values $values -Name 'FOUNDRY_ACCOUNT_NAME' -Fallback (Get-EnvValue -Values $values -Name 'AZURE_AI_ACCOUNT_NAME')
$projectName = Get-EnvValue -Values $values -Name 'FOUNDRY_PROJECT_NAME' -Fallback (Get-EnvValue -Values $values -Name 'AZURE_AI_PROJECT_NAME')
$endpoint = Get-EnvValue -Values $values -Name 'AZURE_AI_PROJECT_ENDPOINT'
if (-not $accountName -and $endpoint) {
    try { $accountName = ([uri]$endpoint).Host.Split('.')[0] } catch { }
}
if (-not $projectName -and $endpoint) {
    $endpointParts = ([uri]$endpoint).AbsolutePath.Trim('/').Split('/')
    if ($endpointParts.Length -ge 3 -and $endpointParts[0] -eq 'api' -and $endpointParts[1] -eq 'projects') { $projectName = $endpointParts[2] }
}
if (-not $script:subscription -or -not $resourceGroup -or -not $accountName) {
    throw 'Missing target values. Provide AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, and the existing account name or AZURE_AI_PROJECT_ENDPOINT in the selected .env.'
}
if (-not $projectName) { $projectName = 'email-workshop' }

Ensure-AzureCli
Ensure-Login
Write-Host "Checking existing Foundry account '$accountName' in resource group '$resourceGroup'..." -ForegroundColor Cyan
$account = Invoke-AzJson -Arguments @('cognitiveservices', 'account', 'show', '--subscription', $script:subscription, '--resource-group', $resourceGroup, '--name', $accountName, '--output', 'json')
if ($account.kind -ne 'AIServices') { throw "Target account '$accountName' is not kind AIServices; refusing deployment." }
if (-not $location) { $location = [string]$account.location }
if (-not $location) { throw 'Could not resolve the existing account region; set FOUNDRY_LOCATION in the environment file.' }

Ensure-MlExtension
do {
    $filterInput = Read-Host "Filter model names by regex (case-insensitive) [$ModelFilter]; enter * to show all"
    if ($filterInput -eq '*') {
        $ModelFilter = ''
    } elseif (-not [string]::IsNullOrWhiteSpace($filterInput)) {
        $ModelFilter = $filterInput.Trim()
    }
    try {
        if ($ModelFilter) {
            $null = [regex]::new($ModelFilter, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        }
        $validModelFilter = $true
    } catch [System.ArgumentException] {
        Write-Host "Invalid regex: $($_.Exception.Message)" -ForegroundColor Yellow
        $validModelFilter = $false
    }
} until ($validModelFilter)
$models = @(Read-ModelNames -Filter $ModelFilter)
if ($models.Count -eq 0) {
    $shownFilter = if ($ModelFilter) { $ModelFilter } else { 'all model names' }
    $newFilter = Read-Host "No matches for '$shownFilter'. Enter another model-name filter (blank to stop)"
    if (-not $newFilter) { throw 'No model was selected; no proposal was written.' }
    $models = @(Read-ModelNames -Filter $newFilter)
}
if ($models.Count -eq 0) { throw 'No matching model names were returned from the azure-huggingface registry.' }

Write-Host ''
Write-Host 'Matching model names from azure-huggingface registry:' -ForegroundColor Cyan
for ($index = 0; $index -lt $models.Count; $index++) {
    $item = $models[$index]
    Write-Host ("{0,2}. {1}  latest version {2}" -f ($index + 1), $item.name, $item.'latest version')
}
$selectedModelName = Select-NumberedItem -Items $models -Prompt 'Select a model name number'
$versions = @(Read-ModelVersions -Name ([string]$selectedModelName.name))

Write-Host ''
Write-Host "Published versions for $($selectedModelName.name):" -ForegroundColor Cyan
for ($index = 0; $index -lt $versions.Count; $index++) {
    Write-Host ("{0,2}. version {1}" -f ($index + 1), $versions[$index].version)
}
$selectedModel = Select-NumberedItem -Items $versions -Prompt 'Select a version number'
$modelUri = if ($selectedModel.id -match '/versions/[^/\s]+$') {
    [string]$selectedModel.id
} else {
    "azureml://registries/azure-huggingface/models/$($selectedModel.name)/versions/$($selectedModel.version)"
}

Write-Host "Validating selected model with az ml model show: $($selectedModel.name) version $($selectedModel.version)" -ForegroundColor Cyan
$selectedModelDetails = Invoke-AzJson -Arguments @('ml', 'model', 'show', '--registry-name', 'azure-huggingface', '--name', [string]$selectedModel.name, '--version', [string]$selectedModel.version, '--output', 'json')

$matches = @(Get-ExistingDeploymentMatches -AccountResourceId $account.id -ModelUri $modelUri)
$defaultTemplateVersionUri = ([string]$selectedModelDetails.default_deployment_template.asset_id).Trim()
$templateUri = ''
$accelerator = ''
$allowedTemplateUris = @(
    $selectedModelDetails.allowed_deployment_templates |
        ForEach-Object { ([string]$_.asset_id).Trim() } |
        Where-Object { $_ -match '^azureml://registries/azure-huggingface/deploymenttemplates/[^/\s]+/labels/latest$' }
)
if ($defaultTemplateVersionUri -match '^azureml://registries/azure-huggingface/deploymenttemplates/[^/\s]+/versions/[^/\s]+$') {
    $defaultTemplateLabelUri = $defaultTemplateVersionUri -replace '/versions/[^/\s]+$', '/labels/latest'
    if ($allowedTemplateUris -contains $defaultTemplateLabelUri) {
        $templateUri = $defaultTemplateLabelUri
        Write-Host "Found the model's API-compatible default deployment template label through az ml model show." -ForegroundColor Green
    }
    try {
        $templateDetails = Get-TemplateDetails -TemplateUri $defaultTemplateVersionUri
        $acceleratorChoices = @(
            $templateDetails.acceleratorMaps |
                ForEach-Object { [string]$_.acceleratorType } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Sort-Object -Unique
        )
    } catch {
        Write-Host 'Could not read accelerator metadata through the preview deployment-template command.' -ForegroundColor Yellow
        $acceleratorChoices = @()
    }
    if ($acceleratorChoices.Count -eq 1) {
        $accelerator = $acceleratorChoices[0]
        Write-Host "Resolved accelerator '$accelerator' through az ml deployment-template show." -ForegroundColor Green
    } elseif ($acceleratorChoices.Count -gt 1) {
        Write-Host 'Accelerators supported by the default deployment template:' -ForegroundColor Cyan
        for ($index = 0; $index -lt $acceleratorChoices.Count; $index++) {
            Write-Host ("{0,2}. {1}" -f ($index + 1), $acceleratorChoices[$index])
        }
        $accelerator = Select-NumberedItem -Items $acceleratorChoices -Prompt 'Select an accelerator number'
    }
}
if (-not $templateUri -and $matches.Count -gt 0) {
    Write-Host ''
    Write-Host 'Existing deployments with this exact model URI provide reusable template/accelerator pairs:' -ForegroundColor Cyan
    for ($index = 0; $index -lt $matches.Count; $index++) {
        $item = $matches[$index]
        Write-Host ("{0,2}. {1} | {2} | {3}" -f ($index + 1), $item.name, $item.properties.deploymentTemplate, $item.properties.acceleratorType)
    }
    $reuse = Read-Host 'Select a matching existing pair number, or press Enter to enter a catalog template'
    $reuseNumber = 0
    if ([int]::TryParse($reuse, [ref]$reuseNumber) -and $reuseNumber -ge 1 -and $reuseNumber -le $matches.Count) {
        $templateUri = [string]$matches[$reuseNumber - 1].properties.deploymentTemplate
        $accelerator = [string]$matches[$reuseNumber - 1].properties.acceleratorType
    }
}
if (-not $templateUri) {
    Write-Host ''
    Write-Host 'The selected model did not expose an API-compatible default template label through the installed preview CLI.' -ForegroundColor Yellow
    Write-Host 'Open this selected model in Foundry > Deploy, then copy its exact template URI and supported accelerator.' -ForegroundColor Yellow
    $templateUri = Read-Host 'Deployment template URI (azureml://registries/azure-huggingface/deploymenttemplates/.../labels/latest)'
}
if ($templateUri -notmatch '^azureml://registries/azure-huggingface/deploymenttemplates/[^/\s]+/labels/latest$') {
    throw 'Template URI must be an azure-huggingface deploymenttemplates URI ending in /labels/latest, as required by the managed-compute API.'
}
if (-not $accelerator) {
    Write-Host 'Do not guess the accelerator value; copy it from the selected template details.' -ForegroundColor Yellow
    $accelerator = Read-Host 'Exact accelerator type supported by this model/template'
}
if (-not $accelerator -or $accelerator -match '\s') { throw 'Enter the exact non-empty accelerator enum from the Foundry Deploy details.' }

$defaultDeploymentName = Get-EnvValue -Values $values -Name 'FOUNDRY_DEPLOYMENT_NAME' -Fallback 'nemotron-email'
$deploymentName = Read-Host "Deployment name [$defaultDeploymentName]"
if (-not $deploymentName) { $deploymentName = $defaultDeploymentName }
$targetProject = Read-Host "Project to create/update under the existing Foundry account [$projectName]"
if (-not $targetProject) { $targetProject = $projectName }
$defaultCapacity = Get-EnvValue -Values $values -Name 'FOUNDRY_CAPACITY' -Fallback '1'
$capacityInput = Read-Host "Model instance capacity [$defaultCapacity]"
if (-not $capacityInput) { $capacityInput = $defaultCapacity }
$capacityNumber = 0
if (-not [int]::TryParse($capacityInput, [ref]$capacityNumber) -or $capacityNumber -lt 1) { throw 'Capacity must be a positive integer.' }

$proposal = @(
    '# Local proposal. Review before deployment; this file is ignored by Git.',
    '# Existing Foundry account is reused; only the project and managed-compute deployment are targeted.',
    "AZURE_SUBSCRIPTION_ID=$script:subscription",
    "FOUNDRY_RESOURCE_GROUP=$resourceGroup",
    "FOUNDRY_LOCATION=$location",
    "FOUNDRY_ACCOUNT_NAME=$accountName",
    "FOUNDRY_PROJECT_NAME=$targetProject",
    "FOUNDRY_DEPLOYMENT_NAME=$deploymentName",
    "FOUNDRY_MODEL_ID=$modelUri",
    "FOUNDRY_DEPLOYMENT_TEMPLATE_ID=$templateUri",
    "FOUNDRY_ACCELERATOR_TYPE=$accelerator",
    "FOUNDRY_CAPACITY=$capacityNumber",
    'FOUNDRY_DEPLOYMENT_APPROVED=false',
    ''
)
if (Test-Path $proposalPath) {
    $overwrite = Read-Host "Proposal exists at $proposalPath. Overwrite it? [y/N]"
    if ($overwrite -notmatch '^(y|yes)$') { throw 'Proposal was not overwritten; no deployment was attempted.' }
}
Set-Content -LiteralPath $proposalPath -Value $proposal -Encoding UTF8
Write-Host ''
Write-Host "Proposal written: $proposalPath" -ForegroundColor Green
Write-Host "Selected model URI: $modelUri"
Write-Host "Selected template URI: $templateUri"
Write-Host "Selected accelerator: $accelerator"
Write-Host 'Proposal approval remains false. No Azure resources have been deployed yet.' -ForegroundColor Green

$deployNow = Read-Host 'Deploy this project/model now? This provisions billable managed GPU capacity. Type DEPLOY to continue'
if ($deployNow -cne 'DEPLOY') {
    Write-Host 'Stopped after proposal generation. No Azure resources were deployed.' -ForegroundColor Yellow
    return
}
$costApproval = Read-Host 'Confirm license/terms, managed-compute quota, region capacity, and pricing by typing APPROVED'
if ($costApproval -cne 'APPROVED') { throw 'Deployment not approved; proposal remains available and no resources were deployed.' }

$environmentValues = @{
    AZURE_SUBSCRIPTION_ID = $script:subscription
    FOUNDRY_RESOURCE_GROUP = $resourceGroup
    FOUNDRY_LOCATION = $location
    FOUNDRY_ACCOUNT_NAME = $accountName
    FOUNDRY_PROJECT_NAME = $targetProject
    FOUNDRY_DEPLOYMENT_NAME = $deploymentName
    FOUNDRY_MODEL_ID = $modelUri
    FOUNDRY_DEPLOYMENT_TEMPLATE_ID = $templateUri
    FOUNDRY_ACCELERATOR_TYPE = $accelerator
    FOUNDRY_CAPACITY = [string]$capacityNumber
    FOUNDRY_DEPLOYMENT_APPROVED = 'true'
}
$previousValues = @{}
foreach ($name in $environmentValues.Keys) {
    $previousValues[$name] = [Environment]::GetEnvironmentVariable($name)
    [Environment]::SetEnvironmentVariable($name, [string]$environmentValues[$name], 'Process')
}
try {
    Push-Location $workshopRoot
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        & $uv.Source run --extra cloud --extra dev python -m email_workshop.foundry_deploy --env-file $resolvedEnvFile --apply
    } else {
        $python = Join-Path $workshopRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path $python)) { throw 'Install uv or create the workshop .venv before deploying.' }
        & $python -m email_workshop.foundry_deploy --env-file $resolvedEnvFile --apply
    }
    if ($LASTEXITCODE -ne 0) { throw "Foundry deployment failed with exit code $LASTEXITCODE." }
    Write-Host ''
    Write-Host 'When the workshop is finished, remove the billable model deployment with:' -ForegroundColor Yellow
    Write-Host '.\scripts\foundry_teardown.ps1'
} finally {
    Pop-Location
    foreach ($name in $environmentValues.Keys) { [Environment]::SetEnvironmentVariable($name, $previousValues[$name], 'Process') }
}
