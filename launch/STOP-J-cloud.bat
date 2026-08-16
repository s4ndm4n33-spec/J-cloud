@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ===========================================================================
REM J-cloud Sovereign Shard — Stopper
REM
REM Kills only shard-owned processes by reading data/run/pids.txt.
REM Falls back to port-based kill only if the PID file is missing.
REM Never kills processes that were not started by J-cloud.bat.
REM ===========================================================================

set "SHARD_ROOT=%~dp0.."
for %%I in ("%SHARD_ROOT%") do set "SHARD_ROOT=%%~fI"
set "PID_FILE=%SHARD_ROOT%\data\run\pids.txt"

echo [J-CLOUD] Stopping sovereign shard processes...

set "KILLED=0"

if exist "%PID_FILE%" (
    for /f "tokens=1" %%P in (%PID_FILE%) do (
        taskkill /PID %%P /T /F >nul 2>&1
        if !errorlevel! equ 0 (
            echo [J-CLOUD] Killed PID %%P
            set "KILLED=1"
        )
    )
    del "%PID_FILE%" >nul 2>&1
) else (
    echo [J-CLOUD] No PID file found. Falling back to port-based detection...
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8001 .*LISTENING" 2^>nul') do (
        taskkill /PID %%P /T /F >nul 2>&1
        if !errorlevel! equ 0 echo [J-CLOUD] Killed backend on port 8001 (PID %%P)
    )
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":3000 .*LISTENING" 2^>nul') do (
        taskkill /PID %%P /T /F >nul 2>&1
        if !errorlevel! equ 0 echo [J-CLOUD] Killed frontend on port 3000 (PID %%P)
    )
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8080 .*LISTENING" 2^>nul') do (
        taskkill /PID %%P /T /F >nul 2>&1
        if !errorlevel! equ 0 echo [J-CLOUD] Killed model server on port 8080 (PID %%P)
    )
)

if "!KILLED!"=="0" (
    echo [J-CLOUD] No shard processes were running.
) else (
    echo [J-CLOUD] Shard stopped.
)

endlocal
