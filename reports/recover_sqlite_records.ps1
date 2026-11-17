param([switch]$Apply)
$ErrorActionPreference = "Stop"
$projectPath = Split-Path -Parent $PSScriptRoot
$taskCredential = Import-Clixml -LiteralPath (Join-Path $projectPath '.secrets\postgres.xml')
$taskDatabase = Get-Content -LiteralPath (Join-Path $projectPath '.secrets\postgres.json') -Raw | ConvertFrom-Json
if ($taskCredential.UserName -ne $taskDatabase.User) {
    throw "Stored database credential and configuration do not match."
}
$env:ARALHUB_AUDIT_DB_NAME = $taskDatabase.Name
$env:ARALHUB_AUDIT_DB_USER = $taskDatabase.User
$env:ARALHUB_AUDIT_DB_HOST = $taskDatabase.Host
$env:ARALHUB_AUDIT_DB_PORT = $taskDatabase.Port
$env:ARALHUB_AUDIT_DB_PASSWORD = $taskCredential.GetNetworkCredential().Password
try {
    $recoveryArgs = @((Join-Path $PSScriptRoot 'recover_sqlite_records.py'))
    if ($Apply) { $recoveryArgs += '--apply' }
    & (Join-Path $projectPath '.venv\Scripts\python.exe') @recoveryArgs
    if ($LASTEXITCODE -ne 0) { throw "SQLite recovery did not complete." }
}
finally {
    Remove-Item Env:ARALHUB_AUDIT_DB_PASSWORD -ErrorAction SilentlyContinue
    $taskCredential = $null
}
