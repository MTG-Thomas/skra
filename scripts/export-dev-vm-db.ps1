param(
    [string]$VmHost = "skra-dev.netbird.cloud",
    [string]$VmUser = "thomas",
    [string]$DeployRoot = "/home/thomas/deploy/skra-main",
    [string]$ComposeProject = "skra-dev",
    [string]$OutputDirectory = ".migration-runs/azure-neon-proof",
    [string]$OutputPrefix = "skra-dev"
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$localOutput = Join-Path $OutputDirectory $timestamp
New-Item -ItemType Directory -Force -Path $localOutput | Out-Null

$remoteDump = "/tmp/$OutputPrefix-$timestamp.dump"
$remoteStats = "/tmp/$OutputPrefix-$timestamp-stats.txt"
$localDump = Join-Path $localOutput "$OutputPrefix.dump"
$localStats = Join-Path $localOutput "$OutputPrefix-stats.txt"
$compose = "docker compose -p '$ComposeProject' -f docker-compose.yml -f docker-compose.test-vm.yml -f docker-compose.ssl.yml"
$sshOptions = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=NUL"
)

$sshTarget = "$VmUser@$VmHost"
$dumpCommand = "cd '$DeployRoot' && $compose exec -T postgres pg_dump -U skra -d skra --format=custom --no-owner --no-acl > '$remoteDump'"
ssh @sshOptions $sshTarget $dumpCommand
if ($LASTEXITCODE -ne 0) { throw "Remote pg_dump failed with exit code $LASTEXITCODE" }

scp @sshOptions "$sshTarget`:$remoteDump" $localDump
if ($LASTEXITCODE -ne 0) { throw "scp dump failed with exit code $LASTEXITCODE" }

$statsSql = @"
SELECT pg_size_pretty(pg_database_size('skra')) AS database_size;
SELECT 'organizations' AS table_name, COUNT(*) AS row_count FROM organizations
UNION ALL SELECT 'documents', COUNT(*) FROM documents
UNION ALL SELECT 'attachments', COUNT(*) FROM attachments
UNION ALL SELECT 'passwords', COUNT(*) FROM passwords
UNION ALL SELECT 'relationships', COUNT(*) FROM relationships
UNION ALL SELECT 'embedding_index', COUNT(*) FROM embedding_index
ORDER BY table_name;
"@
$statsBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($statsSql))
$statsCommand = "cd '$DeployRoot' && printf '%s' '$statsBase64' | base64 -d | $compose exec -T postgres psql -U skra -d skra -v ON_ERROR_STOP=1 > '$remoteStats'"
ssh @sshOptions $sshTarget $statsCommand
if ($LASTEXITCODE -ne 0) { throw "Remote stats query failed with exit code $LASTEXITCODE" }

scp @sshOptions "$sshTarget`:$remoteStats" $localStats
if ($LASTEXITCODE -ne 0) { throw "scp stats failed with exit code $LASTEXITCODE" }

ssh @sshOptions $sshTarget "rm -f '$remoteDump' '$remoteStats'"

Write-Host "Exported database dump: $localDump"
Write-Host "Exported database stats: $localStats"
