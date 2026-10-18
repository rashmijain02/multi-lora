using './main.bicep'

param location = readEnvironmentVariable('AZURE_LOCATION')
param registryName = readEnvironmentVariable('AZURE_CONTAINER_REGISTRY')
param appName = readEnvironmentVariable('AZURE_CONTAINER_APP')
param image = readEnvironmentVariable('WORKSHOP_CONTAINER_IMAGE')
param foundryUrl = readEnvironmentVariable('FOUNDRY_CHAT_COMPLETIONS_URL')
param foundryModel = readEnvironmentVariable('FOUNDRY_MODEL')
param foundryApiVersion = readEnvironmentVariable('FOUNDRY_API_VERSION', '')
param foundryApiKey = readEnvironmentVariable('FOUNDRY_API_KEY')
param workshopApiToken = readEnvironmentVariable('WORKSHOP_API_TOKEN')
