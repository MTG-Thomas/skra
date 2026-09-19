param(
    [string]$SubscriptionName = "Azure Sponsorship",
    [string]$ResourceGroupName = "rg-skra-neon-dev",
    [string]$Location = "eastus",
    [string]$EnvironmentName = "neon-dev",
    [string]$ApiImage = "",
    [string]$AcrName = "",
    [string]$AcrLoginServer = "",
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrlSync,
    [string]$SkraSecretKey = "",
    [switch]$SkipFrontendBuild,
    [switch]$SkipInitJob
)

$ErrorActionPreference = "Stop"

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

Require-Command az
Require-Command git

if (-not $ApiImage) {
    $shortSha = (git rev-parse --short=7 HEAD).Trim()
    $ApiImage = "ghcr.io/mtg-thomas/skra-api:$shortSha"
}

if (-not $SkraSecretKey) {
    $bytes = [byte[]]::new(48)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $SkraSecretKey = [Convert]::ToBase64String($bytes)
}

Write-Host "Using subscription: $SubscriptionName"
az account set --subscription $SubscriptionName

Write-Host "Ensuring resource group: $ResourceGroupName ($Location)"
az group create --name $ResourceGroupName --location $Location | Out-Null

$placeholderOrigin = "https://placeholder.invalid"
$placeholderRpId = "placeholder.invalid"

Write-Host "Deploying Azure baseline and API container app..."
$deployment = az deployment group create `
    --resource-group $ResourceGroupName `
    --template-file "infra/azure-neon/main.bicep" `
    --parameters `
        location=$Location `
        environmentName=$EnvironmentName `
        apiImage=$ApiImage `
        acrName=$AcrName `
        acrLoginServer=$AcrLoginServer `
        corsOrigins=$placeholderOrigin `
        webauthnRpId=$placeholderRpId `
        webauthnOrigin=$placeholderOrigin `
        skraSecretKey=$SkraSecretKey `
        databaseUrl=$DatabaseUrl `
        databaseUrlSync=$DatabaseUrlSync `
    --query properties.outputs `
    --output json | ConvertFrom-Json

$apiUrl = $deployment.apiUrl.value
$apiFqdn = $deployment.apiFqdn.value
$staticWebsiteUrl = ($deployment.staticWebsiteUrl.value).TrimEnd("/")
$storageAccountName = $deployment.storageAccountName.value
$initJobName = $deployment.initJobName.value
$apiContainerAppName = "ca-skra-api-$EnvironmentName"
$storageKey = az storage account keys list `
    --resource-group $ResourceGroupName `
    --account-name $storageAccountName `
    --query "[0].value" `
    --output tsv

Write-Host "Enabling static website hosting on storage account..."
az storage blob service-properties update `
    --account-name $storageAccountName `
    --account-key $storageKey `
    --static-website `
    --index-document index.html `
    --404-document index.html `
    | Out-Null

Write-Host "API URL: $apiUrl"
Write-Host "Static website URL: $staticWebsiteUrl"

Write-Host "Updating API CORS/WebAuthn origin to static website URL..."
az containerapp update `
    --resource-group $ResourceGroupName `
    --name $apiContainerAppName `
    --set-env-vars `
        "SKRA_CORS_ORIGINS=$staticWebsiteUrl" `
        "SKRA_WEBAUTHN_ORIGIN=$staticWebsiteUrl" `
        "SKRA_WEBAUTHN_RP_ID=$(($staticWebsiteUrl -replace '^https?://','' -replace '/$',''))" `
    | Out-Null

if (-not $SkipInitJob) {
    Write-Host "Starting migration/init job: $initJobName"
    az containerapp job start `
        --resource-group $ResourceGroupName `
        --name $initJobName `
        | Out-Null
}

if (-not $SkipFrontendBuild) {
    Require-Command npm
    Push-Location client
    try {
        Write-Host "Building frontend with VITE_API_URL=$apiUrl"
        $env:VITE_API_URL = $apiUrl
        npm ci
        npm run build
    }
    finally {
        Pop-Location
    }

    Write-Host "Uploading frontend to Azure Storage static website..."
    az storage blob upload-batch `
        --account-name $storageAccountName `
        --account-key $storageKey `
        --destination '$web' `
        --source 'client/dist' `
        --overwrite `
        | Out-Null
}

Write-Host "Proof deployment submitted."
Write-Host "Frontend: $staticWebsiteUrl"
Write-Host "API:      $apiUrl"
Write-Host "Health:   $apiUrl/health"
