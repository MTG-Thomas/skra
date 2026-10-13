$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$scriptPath = Join-Path $repositoryRoot "scripts/export-dev-vm-db.ps1"
$content = Get-Content -LiteralPath $scriptPath -Raw

$tokens = $null
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "export-dev-vm-db.ps1 has PowerShell parse errors: $parseErrors"
}

$forbidden = @(
    "StrictHostKeyChecking=no",
    "UserKnownHostsFile=NUL",
    "UserKnownHostsFile=/dev/null"
)
foreach ($setting in $forbidden) {
    if ($content.Contains($setting)) {
        throw "export-dev-vm-db.ps1 contains forbidden SSH setting: $setting"
    }
}

$required = @(
    'Test-Path -LiteralPath $KnownHostsFile -PathType Leaf',
    'StrictHostKeyChecking=yes',
    'UserKnownHostsFile=$resolvedKnownHosts'
)
foreach ($setting in $required) {
    if (-not $content.Contains($setting)) {
        throw "export-dev-vm-db.ps1 is missing SSH host-key guard: $setting"
    }
}

Write-Host "export-dev-vm-db.ps1 SSH host-key guardrails passed"
