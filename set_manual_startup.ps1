$ErrorActionPreference = "Stop"

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Open PowerShell as Administrator, then rerun this script."
}

$taskName = "AralHub LAN"
$runnerPath = Join-Path $PSScriptRoot "start_aralhub_postgresql.ps1"
if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) {
    throw "AralHub launcher was not found: $runnerPath"
}

# Update the existing task without changing its Windows account or database credentials.
$taskXml = Export-ScheduledTask -TaskName $taskName
$backupDirectory = Join-Path $PSScriptRoot "backups"
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
$backupPath = Join-Path $backupDirectory ("aralhub_task_before_manual_{0}.xml" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$taskXml | Set-Content -LiteralPath $backupPath -Encoding Unicode

[xml]$definition = $taskXml
$namespaces = New-Object System.Xml.XmlNamespaceManager($definition.NameTable)
$namespaces.AddNamespace("t", $definition.DocumentElement.NamespaceURI)
$triggers = $definition.SelectSingleNode("/t:Task/t:Triggers", $namespaces)
if ($triggers) {
    $triggers.RemoveAll()
}

$action = $definition.SelectSingleNode("/t:Task/t:Actions/t:Exec", $namespaces)
if (-not $action) {
    throw "The existing AralHub task has no executable action. Rerun setup_lan_server.ps1."
}
$action.SelectSingleNode("t:Command", $namespaces).InnerText = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$action.SelectSingleNode("t:Arguments", $namespaces).InnerText = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $runnerPath
$action.SelectSingleNode("t:WorkingDirectory", $namespaces).InnerText = $PSScriptRoot
$startWhenAvailable = $definition.SelectSingleNode("/t:Task/t:Settings/t:StartWhenAvailable", $namespaces)
if ($startWhenAvailable) {
    $startWhenAvailable.InnerText = "false"
}
$allowDemandStart = $definition.SelectSingleNode("/t:Task/t:Settings/t:AllowStartOnDemand", $namespaces)
if ($allowDemandStart) {
    $allowDemandStart.InnerText = "true"
}

Register-ScheduledTask -TaskName $taskName -Xml $definition.OuterXml -Force | Out-Null
$updated = Get-ScheduledTask -TaskName $taskName
if (@($updated.Triggers | Where-Object { $null -ne $_ }).Count -ne 0 -or -not $updated.Settings.AllowDemandStart -or
    $updated.Actions.Arguments -notmatch '-WindowStyle Hidden') {
    throw "The task was updated, but manual startup verification failed. Check Task Scheduler."
}

Write-Host "AralHub no longer starts automatically at boot or sign-in."
Write-Host "In Task Scheduler, select 'AralHub LAN' and click Run to enable client access. PowerShell stays hidden."
Write-Host "Previous task configuration: $backupPath"
