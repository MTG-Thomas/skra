@description('Azure region for Skra proof resources.')
param location string = resourceGroup().location

@description('Short environment name used in resource names.')
param environmentName string = 'neon-dev'

@description('Pinned API image published by CI, e.g. ghcr.io/mtg-thomas/skra-api:abcdef1.')
param apiImage string

@description('Optional Azure Container Registry login server, e.g. myregistry.azurecr.io.')
param acrLoginServer string = ''

@description('Optional Azure Container Registry name. When set, the API Container App gets AcrPull via managed identity.')
param acrName string = ''

@description('Container App external API hostname CORS origin, e.g. https://docs-proof.example.com. Use the generated hostname until custom DNS exists.')
param corsOrigins string

@description('WebAuthn RP ID for the proof hostname.')
param webauthnRpId string

@description('WebAuthn origin URL for the proof hostname.')
param webauthnOrigin string

@secure()
@description('Skra JWT/encryption secret.')
param skraSecretKey string

@secure()
@description('Neon async SQLAlchemy URL, postgresql+asyncpg://...')
param databaseUrl string

@secure()
@description('Neon sync SQLAlchemy URL, postgresql://...')
param databaseUrlSync string

@description('Minimum API replicas. Use 0 for the lowest-cost proof.')
param apiMinReplicas int = 0

@description('Maximum API replicas.')
param apiMaxReplicas int = 2

var normalizedEnvironment = toLower(replace(environmentName, '-', ''))
var suffix = uniqueString(resourceGroup().id, environmentName)
var storageName = take('bifdocs${normalizedEnvironment}${suffix}', 24)
var logName = 'log-skra-${environmentName}'
var appInsightsName = 'appi-skra-${environmentName}'
var containerEnvName = 'cae-skra-${environmentName}'
var apiName = 'ca-skra-api-${environmentName}'
var initJobName = 'caj-skra-init-${environmentName}'
var keyVaultName = take('kv-bifdocs-${normalizedEnvironment}-${suffix}', 24)
var attachmentsContainerName = 'attachments'
var backupsContainerName = 'backups'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = if (!empty(acrName)) {
  name: acrName
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource attachments 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: attachmentsContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource backups 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: backupsContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enabledForTemplateDeployment: true
    publicNetworkAccess: 'Enabled'
  }
}

resource secretSkraKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'skra-secret-key'
  properties: {
    value: skraSecretKey
  }
}

resource secretDatabaseUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'database-url'
  properties: {
    value: databaseUrl
  }
}

resource secretDatabaseUrlSync 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'database-url-sync'
  properties: {
    value: databaseUrlSync
  }
}

resource secretStorageKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'storage-account-key'
  properties: {
    value: storage.listKeys().keys[0].value
  }
}

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
      }
      registries: empty(acrLoginServer) ? [] : [
        {
          server: acrLoginServer
          identity: 'system'
        }
      ]
      secrets: [
        {
          name: 'skra-secret-key'
          value: skraSecretKey
        }
        {
          name: 'database-url'
          value: databaseUrl
        }
        {
          name: 'database-url-sync'
          value: databaseUrlSync
        }
        {
          name: 'storage-account-key'
          value: storage.listKeys().keys[0].value
        }
      ]
    }
    template: {
      scale: {
        minReplicas: apiMinReplicas
        maxReplicas: apiMaxReplicas
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '25'
              }
            }
          }
        ]
      }
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'SKRA_ENVIRONMENT'
              value: 'production'
            }
            {
              name: 'SKRA_DEBUG'
              value: 'false'
            }
            {
              name: 'SKRA_RATE_LIMITING_ENABLED'
              value: 'false'
            }
            {
              name: 'SKRA_SECRET_KEY'
              secretRef: 'skra-secret-key'
            }
            {
              name: 'SKRA_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'SKRA_DATABASE_URL_SYNC'
              secretRef: 'database-url-sync'
            }
            {
              name: 'SKRA_CORS_ORIGINS'
              value: corsOrigins
            }
            {
              name: 'SKRA_WEBAUTHN_RP_ID'
              value: webauthnRpId
            }
            {
              name: 'SKRA_WEBAUTHN_ORIGIN'
              value: webauthnOrigin
            }
            {
              name: 'SKRA_STORAGE_BACKEND'
              value: 'azure_blob'
            }
            {
              name: 'SKRA_AZURE_STORAGE_ACCOUNT_URL'
              value: storage.properties.primaryEndpoints.blob
            }
            {
              name: 'SKRA_AZURE_STORAGE_ACCOUNT_KEY'
              secretRef: 'storage-account-key'
            }
            {
              name: 'SKRA_AZURE_BLOB_CONTAINER'
              value: attachmentsContainerName
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsights.properties.ConnectionString
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
          ]
        }
      ]
    }
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acrName)) {
  name: guid(api.id, acr.id, 'acrpull')
  scope: acr
  properties: {
    principalId: api.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
  }
}

resource initJob 'Microsoft.App/jobs@2024-03-01' = {
  name: initJobName
  location: location
  properties: {
    environmentId: containerEnv.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 900
      replicaRetryLimit: 1
      manualTriggerConfig: {
        replicaCompletionCount: 1
          parallelism: 1
        }
      secrets: [
        {
          name: 'skra-secret-key'
          value: skraSecretKey
        }
        {
          name: 'database-url'
          value: databaseUrl
        }
        {
          name: 'database-url-sync'
          value: databaseUrlSync
        }
        {
          name: 'storage-account-key'
          value: storage.listKeys().keys[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'init'
          image: apiImage
          command: [
            'python'
            '-m'
            'scripts.init_container'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'SKRA_ENVIRONMENT'
              value: 'production'
            }
            {
              name: 'SKRA_SECRET_KEY'
              secretRef: 'skra-secret-key'
            }
            {
              name: 'SKRA_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'SKRA_DATABASE_URL_SYNC'
              secretRef: 'database-url-sync'
            }
          ]
        }
      ]
    }
  }
}

output apiFqdn string = api.properties.configuration.ingress.fqdn
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output storageAccountName string = storage.name
output keyVaultName string = keyVault.name
output staticWebsiteUrl string = storage.properties.primaryEndpoints.web
output attachmentsContainer string = attachmentsContainerName
output backupsContainer string = backupsContainerName
output initJobName string = initJob.name
