# Retire all SQLite files in this project without creating any backup.
# PostgreSQL records are verified read-only before deleting the SQLite source.
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path -LiteralPath $PSScriptRoot).Path.TrimEnd('\')
$projectPrefix = $projectPath + '\'
$databaseSettings = Get-Content -LiteralPath (Join-Path $projectPath '.secrets\postgres.json') -Raw | ConvertFrom-Json
$databaseCredential = Import-Clixml -LiteralPath (Join-Path $projectPath '.secrets\postgres.xml')
if ($databaseCredential.UserName -ne $databaseSettings.User) {
    throw 'The PostgreSQL credential does not match the configured database user.'
}
$env:ARALHUB_CLEANUP_DB_NAME = $databaseSettings.Name
$env:ARALHUB_CLEANUP_DB_USER = $databaseSettings.User
$env:ARALHUB_CLEANUP_DB_HOST = $databaseSettings.Host
$env:ARALHUB_CLEANUP_DB_PORT = $databaseSettings.Port
$env:ARALHUB_CLEANUP_DB_PASSWORD = $databaseCredential.GetNetworkCredential().Password
$env:ARALHUB_CLEANUP_ROOT = $projectPath
try {
    @'
import os, sqlite3
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

with psycopg.connect(
    dbname=os.environ['ARALHUB_CLEANUP_DB_NAME'],
    user=os.environ['ARALHUB_CLEANUP_DB_USER'],
    password=os.environ['ARALHUB_CLEANUP_DB_PASSWORD'],
    host=os.environ['ARALHUB_CLEANUP_DB_HOST'],
    port=os.environ['ARALHUB_CLEANUP_DB_PORT'],
    connect_timeout=5, row_factory=dict_row,
    options='-c default_transaction_read_only=on',
) as target:
    source_path = Path(os.environ['ARALHUB_CLEANUP_ROOT']) / 'exam.db'
    if source_path.is_file():
        with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True) as source:
            source.row_factory = sqlite3.Row
            if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('SQLite integrity check failed; no files deleted.')
            for table in ('students', 'exams', 'questions', 'results', 'portal_submissionreturn'):
                saved = {row['id']: row for row in target.execute(f'SELECT * FROM "{table}"')}
                for row in source.execute(f'SELECT * FROM "{table}"'):
                    if row['id'] not in saved:
                        raise SystemExit(f'A {table} record is missing from PostgreSQL; no files deleted.')
                    actual = saved[row['id']]
                    for column in row.keys():
                        equal = (abs(row[column] - actual[column]) < 0.00001
                                 if table == 'results' and column == 'percent'
                                 else row[column] == actual[column])
                        if not equal:
                            raise SystemExit(f'A {table} record differs in PostgreSQL; no files deleted.')
    print('PostgreSQL verified. No backup was created.')
'@ | & (Join-Path $projectPath '.venv\Scripts\python.exe') -
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL verification failed; no files deleted.' }
}
finally {
    Remove-Item Env:ARALHUB_CLEANUP_DB_PASSWORD -ErrorAction SilentlyContinue
    $databaseCredential = $null
}

$databaseFiles = @(Get-ChildItem -LiteralPath $projectPath -Recurse -Force -File |
    Where-Object { $_.Name -match '\.(db|sqlite|sqlite3)(-(wal|shm|journal)|\.(bak|backup))?$' })
foreach ($databaseFile in $databaseFiles) {
    $resolvedFile = (Resolve-Path -LiteralPath $databaseFile.FullName).Path
    if (-not $resolvedFile.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        ($databaseFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing an unsafe deletion target: $resolvedFile"
    }
}
$deletedFiles = @()
foreach ($databaseFile in $databaseFiles) {
    if ($PSCmdlet.ShouldProcess($databaseFile.FullName, 'Permanently delete retired SQLite file without backup')) {
        Remove-Item -LiteralPath $databaseFile.FullName -Force -ErrorAction Stop
        $deletedFiles += $databaseFile.FullName
    }
}
if (-not $WhatIfPreference) {
    $remainingFiles = @(Get-ChildItem -LiteralPath $projectPath -Recurse -Force -File |
        Where-Object { $_.Name -match '\.(db|sqlite|sqlite3)(-(wal|shm|journal)|\.(bak|backup))?$' })
    if ($remainingFiles.Count) { throw 'SQLite files remain; cleanup did not fully complete.' }
    [ordered]@{
        deleted_sqlite_files = $deletedFiles.Count
        deleted_paths = $deletedFiles
        remaining_sqlite_files = 0
        backup_created = $false
        postgresql_records_verified = $true
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $projectPath 'reports\postgresql_only_cleanup.json') -Encoding UTF8
    Write-Output "Deleted $($deletedFiles.Count) SQLite file(s). PostgreSQL remains the live database. No backup created."
}
