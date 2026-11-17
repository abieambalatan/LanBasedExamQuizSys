$ErrorActionPreference = "Stop"

$projectPath = $PSScriptRoot
$taskName = "AralHub LAN"
$pythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
$runnerPath = Join-Path $projectPath "start_aralhub_postgresql.ps1"
$pgIsReadyPath = "C:\Program Files\PostgreSQL\18\bin\pg_isready.exe"
$credentialDirectory = Join-Path $projectPath ".secrets"
$credentialPath = Join-Path $credentialDirectory "postgres.xml"
$databaseSettingsPath = Join-Path $credentialDirectory "postgres.json"

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Open PowerShell as Administrator, then rerun this script."
}

foreach ($path in @($pythonPath, $runnerPath, $pgIsReadyPath)) {
    if (-not (Test-Path $path -PathType Leaf)) {
        throw "Required file was not found: $path"
    }
}

$portalListener = Get-NetTCPConnection -State Listen -LocalPort 5000 -ErrorAction SilentlyContinue
if ($portalListener) {
    throw "Stop the currently running AralHub server before setting up its scheduled task."
}

& $pgIsReadyPath -h 127.0.0.1 -p 5432
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL is not accepting connections on 127.0.0.1:5432."
}

New-Item -ItemType Directory -Path $credentialDirectory -Force | Out-Null
$userSid = $identity.User
$systemSid = New-Object System.Security.Principal.SecurityIdentifier("S-1-5-18")
$inheritanceFlags = [System.Security.AccessControl.InheritanceFlags](
    [int][System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [int][System.Security.AccessControl.InheritanceFlags]::ObjectInherit
)

$postgresCredential = $null
$databaseSettings = $null
if ((Test-Path $credentialPath -PathType Leaf) -and (Test-Path $databaseSettingsPath -PathType Leaf)) {
    $savedCredential = Import-Clixml -LiteralPath $credentialPath
    $savedSettings = Get-Content -LiteralPath $databaseSettingsPath -Raw | ConvertFrom-Json
    if (
        $savedCredential -is [System.Management.Automation.PSCredential] -and
        $savedCredential.UserName -eq $savedSettings.User -and
        $savedSettings.Name -and
        $savedSettings.Host -and
        $savedSettings.Port
    ) {
        $reuseSavedSettings = Read-Host "Reuse saved PostgreSQL settings for $($savedSettings.Name) as $($savedSettings.User)? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($reuseSavedSettings) -or $reuseSavedSettings -match '^(?i:y|yes)$') {
            $postgresCredential = $savedCredential
            $databaseSettings = $savedSettings
        }
    }
}

if (-not $postgresCredential) {
    $databaseName = Read-Host "PostgreSQL database name [aralhub]"
    if ([string]::IsNullOrWhiteSpace($databaseName)) {
        $databaseName = "aralhub"
    }

    $databaseUser = Read-Host "PostgreSQL application role [aralhub_app]"
    if ([string]::IsNullOrWhiteSpace($databaseUser)) {
        $databaseUser = "aralhub_app"
    }

    $postgresPassword = Read-Host "PostgreSQL application password" -AsSecureString
    $postgresCredential = [System.Management.Automation.PSCredential]::new($databaseUser, $postgresPassword)
    $databaseSettings = [ordered]@{
        Name = $databaseName
        User = $databaseUser
        Host = "127.0.0.1"
        Port = "5432"
    }
} else {
    $postgresPassword = $postgresCredential.Password
    $databaseName = $databaseSettings.Name
    $databaseUser = $databaseSettings.User
}

$directoryAcl = New-Object System.Security.AccessControl.DirectorySecurity
$directoryAcl.SetAccessRuleProtection($true, $false)
$directoryAcl.SetOwner($userSid)
$directoryAcl.AddAccessRule(
    (New-Object System.Security.AccessControl.FileSystemAccessRule(
        $userSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        $inheritanceFlags,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    ))
)
$directoryAcl.AddAccessRule(
    (New-Object System.Security.AccessControl.FileSystemAccessRule(
        $systemSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        $inheritanceFlags,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    ))
)
Set-Acl -LiteralPath $credentialDirectory -AclObject $directoryAcl
$postgresCredential | Export-Clixml -LiteralPath $credentialPath -Force
$databaseSettings | ConvertTo-Json | Set-Content -LiteralPath $databaseSettingsPath -Encoding UTF8

$fileAcl = New-Object System.Security.AccessControl.FileSecurity
$fileAcl.SetAccessRuleProtection($true, $false)
$fileAcl.SetOwner($userSid)
$fileAcl.AddAccessRule(
    (New-Object System.Security.AccessControl.FileSystemAccessRule(
        $userSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    ))
)
$fileAcl.AddAccessRule(
    (New-Object System.Security.AccessControl.FileSystemAccessRule(
        $systemSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    ))
)
Set-Acl -LiteralPath $credentialPath -AclObject $fileAcl
Set-Acl -LiteralPath $databaseSettingsPath -AclObject $fileAcl

$passwordPointer = [IntPtr]::Zero
try {
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($postgresPassword)
    $env:EXAM_PORTAL_DB_ENGINE = "postgresql"
    $env:EXAM_PORTAL_DB_NAME = $databaseName
    $env:EXAM_PORTAL_DB_USER = $databaseUser
    $env:EXAM_PORTAL_DB_HOST = $databaseSettings.Host
    $env:EXAM_PORTAL_DB_PORT = $databaseSettings.Port
    $env:EXAM_PORTAL_DB_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)

    @'
import os
import psycopg

with psycopg.connect(
    dbname=os.environ["EXAM_PORTAL_DB_NAME"],
    user=os.environ["EXAM_PORTAL_DB_USER"],
    password=os.environ["EXAM_PORTAL_DB_PASSWORD"],
    host=os.environ["EXAM_PORTAL_DB_HOST"],
    port=os.environ["EXAM_PORTAL_DB_PORT"],
    connect_timeout=5,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user")
        database, user = cursor.fetchone()
        print(f"PostgreSQL credentials verified for database {database} and role {user}.")
'@ | & $pythonPath -
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL login failed. Check the database name, role, and password."
    }

    & $pythonPath (Join-Path $projectPath "manage.py") check
    if ($LASTEXITCODE -ne 0) {
        throw "Django check failed. The scheduled task was not registered."
    }
}
finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    Remove-Item Env:EXAM_PORTAL_DB_PASSWORD -ErrorAction SilentlyContinue
    $postgresPassword.Dispose()
}

$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $runnerPath) `
    -WorkingDirectory $projectPath
$taskPrincipal = New-ScheduledTaskPrincipal `
    -UserId $identity.Name `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Force | Out-Null

$ruleExists = Get-NetFirewallRule -DisplayName "AralHub LAN" -ErrorAction SilentlyContinue
if (-not $ruleExists) {
    New-NetFirewallRule `
        -DisplayName "AralHub LAN" `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 5000 | Out-Null
}

Write-Host "Task Scheduler is configured to start AralHub with PostgreSQL only when you run the task."
Write-Host "The PostgreSQL password is encrypted for this Windows account in .secrets\postgres.xml."
Write-Host "After signing in, open Task Scheduler, select 'AralHub LAN', and click Run. PowerShell stays hidden."
Write-Host "AralHub does not start automatically at boot or sign-in. Do not start a second server while the task is running."
Write-Host "Student URL: http://<SERVER-IP>:5000"
