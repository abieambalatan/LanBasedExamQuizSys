$ErrorActionPreference = "Stop"

$projectPath = $PSScriptRoot
# Attach before starting any children. A PowerShell finally block cannot run
# when Task Scheduler forcibly ends the task; Windows owns this cleanup instead.
Add-Type -Path (Join-Path $projectPath "launcher_process_job.cs")
[AralHubProcessJob]::AttachLauncher()

$credentialPath = Join-Path $projectPath ".secrets\postgres.xml"
$databaseSettingsPath = Join-Path $projectPath ".secrets\postgres.json"
$pythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
$pgIsReadyPath = "C:\Program Files\PostgreSQL\18\bin\pg_isready.exe"
$logDirectory = Join-Path $projectPath "logs"

foreach ($path in @($credentialPath, $databaseSettingsPath, $pythonPath, $pgIsReadyPath)) {
    if (-not (Test-Path $path -PathType Leaf)) {
        throw "Required PostgreSQL startup file was not found: $path"
    }
}

$credential = Import-Clixml -LiteralPath $credentialPath
if (-not ($credential -is [System.Management.Automation.PSCredential])) {
    throw "The encrypted PostgreSQL credential file is invalid. Rerun setup_lan_server.ps1."
}
$databaseSettings = Get-Content -LiteralPath $databaseSettingsPath -Raw | ConvertFrom-Json
if (-not $databaseSettings.Name -or -not $databaseSettings.User -or -not $databaseSettings.Host -or -not $databaseSettings.Port) {
    throw "PostgreSQL connection settings are invalid. Rerun setup_lan_server.ps1."
}

$env:EXAM_PORTAL_DB_ENGINE = "postgresql"
$env:EXAM_PORTAL_DB_NAME = $databaseSettings.Name
$env:EXAM_PORTAL_DB_USER = $databaseSettings.User
$env:EXAM_PORTAL_DB_HOST = $databaseSettings.Host
$env:EXAM_PORTAL_DB_PORT = $databaseSettings.Port
if ($credential.UserName -ne $databaseSettings.User) {
    throw "PostgreSQL credential does not match the configured database user. Rerun setup_lan_server.ps1."
}
$passwordPointer = [IntPtr]::Zero

try {
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)
    $env:EXAM_PORTAL_DB_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)

    $deadline = (Get-Date).AddMinutes(5)
    $postgresReady = $false
    do {
        & $pgIsReadyPath -h $env:EXAM_PORTAL_DB_HOST -p $env:EXAM_PORTAL_DB_PORT *> $null
        if ($LASTEXITCODE -eq 0) {
            $postgresReady = $true
            break
        }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)

    if (-not $postgresReady) {
        throw "PostgreSQL did not become ready at 127.0.0.1:5432 within five minutes."
    }

    $existingListener = Get-NetTCPConnection -State Listen -LocalPort 5000 -ErrorAction SilentlyContinue
    if ($existingListener) {
        throw "Port 5000 is already in use. Refusing to start a duplicate AralHub server."
    }

    & $pythonPath (Join-Path $projectPath "manage.py") migrate --noinput
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL Django migrations failed; AralHub was not started."
    }

    & $pythonPath (Join-Path $projectPath "manage.py") bootstrap_superadmin
    if ($LASTEXITCODE -ne 0) {
        throw "Django superadmin check failed; AralHub was not started."
    }

    & $pythonPath (Join-Path $projectPath "manage.py") check
    if ($LASTEXITCODE -ne 0) {
        throw "Django system check failed; AralHub was not started."
    }

    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLog = Join-Path $logDirectory "postgresql_$timestamp.stdout.log"
    $stderrLog = Join-Path $logDirectory "postgresql_$timestamp.stderr.log"

    $server = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList ('"{0}"' -f (Join-Path $projectPath "app.py")) `
        -WorkingDirectory $projectPath `
        -Wait `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog

    if ($server.ExitCode -ne 0) {
        throw "AralHub exited with code $($server.ExitCode). Review logs\postgresql_$timestamp.*.log."
    }
}
finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    Remove-Item Env:EXAM_PORTAL_DB_PASSWORD -ErrorAction SilentlyContinue
    $credential = $null
}
