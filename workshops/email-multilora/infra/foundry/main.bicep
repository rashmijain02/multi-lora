targetScope = 'resourceGroup'

param location string = resourceGroup().location
@minLength(2)
@maxLength(64)
param accountName string
param projectName string
@minLength(1)
@maxLength(64)
param deploymentName string
@description('Exact versioned model asset URI copied from the Foundry catalog.')
param modelId string
@description('Compatible versioned deployment template URI copied from the deployment wizard.')
param deploymentTemplateId string
@description('Accelerator type supported by the selected template and approved quota.')
param acceleratorType string
@minValue(1)
param capacity int = 1

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    // Required for the current workshop's API-key client and public outbound connection.
    disableLocalAuth: false
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: projectName
    description: 'Dedicated managed Nemotron inference for the email workshop.'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/managedComputeDeployments@2026-07-15-preview' = {
  parent: account
  name: deploymentName
  sku: {
    name: 'GlobalManagedCompute'
    capacity: capacity
  }
  properties: {
    model: modelId
    deploymentTemplate: deploymentTemplateId
    acceleratorType: acceleratorType
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [project]
}

output accountResourceId string = account.id
output projectResourceId string = project.id
output deploymentResourceId string = model.id
// No listKeys call: credentials must never become deployment outputs.
output chatCompletionsUrl string = 'https://${accountName}.services.ai.azure.com/openai/v1/chat/completions'
output modelDeploymentName string = deploymentName
