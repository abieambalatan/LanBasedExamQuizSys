# Compatibility entry point: the SQLite migration has been retired.
# This starts the PostgreSQL portal and applies its Django migrations only.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "start_aralhub_postgresql.ps1")
