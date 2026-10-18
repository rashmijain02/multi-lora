param location string = resourceGroup().location
param registryName string
param appName string = 'email-workshop'
param image string
param foundryUrl string
param foundryModel string
param foundryApiVersion string = ''
@secure()
param foundryApiKey string
@secure()
@minLength(32)
param workshopApiToken string

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${appName}-pull'
  location: location
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'AcrPull')
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${appName}-env'
  location: location
  properties: {}
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [{
        server: registry.properties.loginServer
        identity: identity.id
      }]
      secrets: [
        { name: 'foundry-key', value: foundryApiKey }
        { name: 'workshop-token', value: workshopApiToken }
      ]
    }
    template: {
      containers: [{
        name: 'api'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'FOUNDRY_CHAT_COMPLETIONS_URL', value: foundryUrl }
          { name: 'FOUNDRY_MODEL', value: foundryModel }
          { name: 'FOUNDRY_API_VERSION', value: foundryApiVersion }
          { name: 'FOUNDRY_API_KEY', secretRef: 'foundry-key' }
          { name: 'WORKSHOP_API_TOKEN', secretRef: 'workshop-token' }
          { name: 'ALLOW_REMOTE_EMAIL', value: 'true' }
        ]
        probes: [
          {
            type: 'Liveness'
            httpGet: { path: '/healthz', port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 30
          }
          {
            type: 'Readiness'
            httpGet: { path: '/healthz', port: 8000 }
            initialDelaySeconds: 5
            periodSeconds: 10
          }
        ]
      }]
      scale: {
        minReplicas: 0
        maxReplicas: 2
        rules: [{
          name: 'http'
          http: { metadata: { concurrentRequests: '8' } }
        }]
      }
    }
  }
  dependsOn: [pull]
}

output apiUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
