@echo off
cd /d "%~dp0"
rem All normal starts use the same PostgreSQL configuration as Task Scheduler.
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0start_aralhub_postgresql.ps1"
exit /b %errorlevel%
