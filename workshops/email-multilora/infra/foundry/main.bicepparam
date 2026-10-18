using './main.bicep'

param location = readEnvironmentVariable('FOUNDRY_LOCATION')
param accountName = readEnvironmentVariable('FOUNDRY_ACCOUNT_NAME')
param projectName = readEnvironmentVariable('FOUNDRY_PROJECT_NAME')
param deploymentName = readEnvironmentVariable('FOUNDRY_DEPLOYMENT_NAME')
param modelId = readEnvironmentVariable('FOUNDRY_MODEL_ID')
param deploymentTemplateId = readEnvironmentVariable('FOUNDRY_DEPLOYMENT_TEMPLATE_ID')
param acceleratorType = readEnvironmentVariable('FOUNDRY_ACCELERATOR_TYPE')
param capacity = int(readEnvironmentVariable('FOUNDRY_CAPACITY', '1'))
