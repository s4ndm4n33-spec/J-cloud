@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ===========================================================================
REM J-cloud Sovereign Shard — Launcher
REM
REM Resolves SHARD_ROOT from its own location, loads portable configuration,
REM validates runtime components, starts backend + frontend, waits for
REM health readiness, and opens the browser. All processes are tracked in
REM data/run/pids.txt so STOP-J-cloud.bat can kill only shard-owned PIDs.
REM ===========================================================================

set "SHARD_ROOT=%~dp0.."
for %%I in ("%SHARD_ROOT%") do set "SHARD_ROOT=%%~fI"

set "CONFIG_DIR=%SHARD_ROOT%\config"
set "DATA_DIR=%SHARD_ROOT%\data"
set "LOG_DIR=%SHARD_ROOT%\logs"
set "RUNTIME_DIR=%SHARD_ROOT%\runtime"
set "RUN_DIR=%DATA_DIR%\run"
set "PID_FILE=%RUN_DIR%\pids.txt"

REM --- Create runtime directories ---
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"
if not exist "%RUN_DIR%" mkdir "%RUN_DIR%"

REM --- Clear stale PID file ---
if exist "%PID_FILE%" del "%PID_FILE%"

REM --- Load portable configuration ---
set "J_CLOUD_PROFILE=portable"
set "J_CLOUD_ROOT=%SHARD_ROOT%"
set "J_CLOUD_DB=%DATA_DIR%\jcloud.db"
set "WORKSPACE_ROOT=%SHARD_ROOT%\workspace"
set "LOCAL_AUTH=1"
set "LOCAL_LLM_BASE_URL=http://127.0.0.1:8080/v1"
set "LOCAL_LLM_MODEL=local-model"
set "CORS_ORIGINS=http://127.0.0.1:3000"
set "REACT_APP_BACKEND_URL=http://127.0.0.1:8001"
set "REACT_APP_J_CLOUD_PROFILE=portable"
set "BACKEND_VERSION=0.1.0"

if exist "%CONFIG_DIR%\sovereign.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in "%CONFIG_DIR%\sovereign.env" do (
        set "_key=%%A"
        set "_val=%%B"
        if not "!_key!"=="" set "!_key!=!_val!"
    )
)

echo.
echo ============================================
echo   J-CLOUD SOVEREIGN SHARD
echo ============================================
echo   Root:     %SHARD_ROOT%
echo   Profile:  %J_CLOUD_PROFILE%
echo   Backend:  http://127.0.0.1:8001
echo   Frontend: http://127.0.0.1:3000
echo ============================================
echo.

REM --- Validate required directories ---
if not exist "%SHARD_ROOT%\backend" (
    echo [ERROR] Backend directory missing at %SHARD_ROOT%\backend
    echo         The shard artifact is incomplete.
    exit /b 3
)

if not exist "%SHARD_ROOT%\frontend\build" (
    echo [ERROR] Frontend production build missing at %SHARD_ROOT%\frontend\build
    echo         Run the release builder first.
    exit /b 4
)

REM --- Resolve Python runtime ---
set "PYTHON="
if exist "%RUNTIME_DIR%\python\python.exe" (
    set "PYTHON=%RUNTIME_DIR%\python\python.exe"
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%P in ('where python') do (
            if not defined PYTHON set "PYTHON=%%P"
        )
        echo [INFO] Bundled Python not found. Using system Python: !PYTHON!
    )
)

if not defined PYTHON (
    echo [ERROR] No Python runtime found.
    echo         Place portable Python at runtime\python\python.exe
    echo         or install Python 3.11+ on the host.
    exit /b 2
)

REM --- Resolve Node runtime ---
set "NODE="
if exist "%RUNTIME_DIR%\node\node.exe" (
    set "NODE=%RUNTIME_DIR%\node\node.exe"
) else (
    where node >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%P in ('where node') do (
            if not defined NODE set "NODE=%%P"
        )
        echo [INFO] Bundled Node not found. Using system Node: !NODE!
    )
)

if not defined NODE (
    echo [WARNING] No Node runtime found.
    echo           Frontend serving requires Node 18+ on the host.
    echo           Backend will start but frontend will be unavailable.
)

REM --- Validate backend port 8001 is available ---
netstat -ano | findstr /R /C:":8001 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo [ERROR] Port 8001 is already in use.
    echo         Run STOP-J-cloud.bat to stop any existing shard, or
    echo         close the application using that port.
    exit /b 5
)

REM --- Validate frontend port 3000 is available ---
netstat -ano | findstr /R /C:":3000 .*LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo [WARNING] Port 3000 is already in use.
    echo           Frontend may not start correctly.
)

REM --- Start optional local model server ---
set "MODEL_PID="
if /i "%LOCAL_LLM_BASE_URL:~0,17%"=="http://127.0.0.1:8080" (
    if exist "%RUNTIME_DIR%\model-server\server.exe" (
        echo [INFO] Starting local model server...
        start "J-cloud Model Server" cmd /c ""%RUNTIME_DIR%\model-server\server.exe" --port 8080 > "%LOG_DIR%\model-server.log" 2>&1"
        for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8080 .*LISTENING" 2^>nul') do (
            set "MODEL_PID=%%P"
        )
        if defined MODEL_PID echo !MODEL_PID!>>"%PID_FILE%"
    ) else (
        echo [INFO] No bundled model server found. Local LLM will be unavailable.
        echo        Core IDE features remain usable without it.
    )
) else (
    echo [INFO] Local LLM URL is not on port 8080 — skipping model server startup.
)

REM --- Start backend ---
echo [INFO] Starting backend...
start "J-cloud Backend" cmd /c ""%PYTHON%" -m uvicorn server:app --host 127.0.0.1 --port 8001 --app-dir "%SHARD_ROOT%\backend" > "%LOG_DIR%\backend.log" 2>&1"

REM Wait for backend to grab the port, then record PID
timeout /t 3 /nobreak >nul
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8001 .*LISTENING" 2^>nul') do (
    set "BACKEND_PID=%%P"
)
if defined BACKEND_PID (
    echo !BACKEND_PID!>>"%PID_FILE%"
    echo [INFO] Backend started (PID: !BACKEND_PID!)
) else (
    echo [ERROR] Backend failed to start. Check %LOG_DIR%\backend.log
    exit /b 6
)

REM --- Wait for backend health ---
echo [INFO] Waiting for backend health...
set "HEALTH_OK=0"
for /L %%i in (1,1,30) do (
    if !HEALTH_OK! equ 0 (
        powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8001/api/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch { exit 1 }" >nul 2>&1
        if !errorlevel! equ 0 (
            set "HEALTH_OK=1"
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)
if !HEALTH_OK! equ 0 (
    echo [ERROR] Backend did not become healthy within 30 seconds.
    echo         Check %LOG_DIR%\backend.log for details.
    exit /b 7
)
echo [INFO] Backend is healthy.

REM --- Check sovereign status ---
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8001/api/sovereign/status' -UseBasicParsing -TimeoutSec 5; $j = $r.Content | ConvertFrom-Json; Write-Host ('  DB:         ' + $j.database); Write-Host ('  Auth:       ' + $j.authentication); Write-Host ('  Workspace:  ' + $j.workspace); Write-Host ('  Local LLM:  ' + $j.local_llm); if ($j.local_llm -eq 'unavailable') { Write-Host '  [NOTE] Local LLM unavailable — J chat will not work until a model server is running.' } } catch { Write-Host '  [WARNING] Could not retrieve sovereign status.' }" 2>nul

REM --- Start frontend production server ---
set "FRONTEND_PID="
if defined NODE (
    if exist "%SHARD_ROOT%\frontend\build" (
        echo [INFO] Starting frontend production server...
        REM Serve the static build with a simple Node HTTP server
        start "J-cloud Frontend" cmd /c ""%NODE%" "%SHARD_ROOT%\launch\serve-build.js" "%SHARD_ROOT%\frontend\build" 3000 > "%LOG_DIR%\frontend.log" 2>&1"
        timeout /t 2 /nobreak >nul
        for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":3000 .*LISTENING" 2^>nul') do (
            set "FRONTEND_PID=%%P"
        )
        if defined FRONTEND_PID (
            echo !FRONTEND_PID!>>"%PID_FILE%"
            echo [INFO] Frontend started (PID: !FRONTEND_PID!)
        ) else (
            echo [WARNING] Frontend may not have started. Check %LOG_DIR%\frontend.log
        )
    ) else (
        echo [WARNING] Frontend build directory missing. Skipping frontend.
    )
) else (
    echo [WARNING] No Node runtime — frontend will not be served.
)

REM --- Open browser ---
timeout /t 2 /nobreak >nul
echo [INFO] Opening browser...
start http://127.0.0.1:3000

echo.
echo ============================================
echo   SHARD IS RUNNING
echo ============================================
echo   Backend:  http://127.0.0.1:8001
echo   Frontend: http://127.0.0.1:3000
echo   Logs:     %LOG_DIR%\
echo   Stop:     launch\STOP-J-cloud.bat
echo ============================================
echo.
endlocal
