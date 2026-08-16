@echo off
setlocal EnableExtensions

set "SHARD_ROOT=%~dp0.."
for %%I in ("%SHARD_ROOT%") do set "SHARD_ROOT=%%~fI"

set "CONFIG_DIR=%SHARD_ROOT%\config"
set "DATA_DIR=%SHARD_ROOT%\data"
set "LOG_DIR=%SHARD_ROOT%\logs"
set "RUNTIME_DIR=%SHARD_ROOT%\runtime"
set "PYTHON=%RUNTIME_DIR%\python\python.exe"
set "NODE=%RUNTIME_DIR%\node\node.exe"

if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"

if not exist "%PYTHON%" (
  echo [J-CLOUD] Portable Python runtime missing.
  echo Run the release setup/assembly process before launching.
  exit /b 2
)

set "J_CLOUD_PROFILE=portable"
set "J_CLOUD_ROOT=%SHARD_ROOT%"
set "J_CLOUD_DB=%DATA_DIR%\jcloud.db"
set "WORKSPACE_ROOT=%SHARD_ROOT%\workspace"
set "LOCAL_AUTH=1"
set "LOCAL_LLM_BASE_URL=http://127.0.0.1:8080/v1"
set "CORS_ORIGINS=http://127.0.0.1:3000"
set "REACT_APP_BACKEND_URL=http://127.0.0.1:8001"
set "REACT_APP_J_CLOUD_PROFILE=portable"

if not exist "%SHARD_ROOT%\backend" (
  echo [J-CLOUD] Backend directory missing.
  exit /b 3
)

if not exist "%SHARD_ROOT%\frontend\node_modules" if exist "%NODE%" (
  echo [J-CLOUD] Frontend dependencies are not assembled.
  echo Run the release builder first.
  exit /b 4
)

start "J-cloud Backend" cmd /k "cd /d ""%SHARD_ROOT%\backend"" && ""%PYTHON%"" -m uvicorn server:app --host 127.0.0.1 --port 8001"

timeout /t 2 /nobreak >nul

if exist "%SHARD_ROOT%\frontend\node_modules" if exist "%NODE%" (
  start "J-cloud Frontend" cmd /k "cd /d ""%SHARD_ROOT%\frontend"" && ""%NODE%"" node_modules\react-scripts\bin\react-scripts.js start"
)

start "J-cloud Browser" http://127.0.0.1:3000

echo.
echo J-CLOUD SOVEREIGN SHARD
echo Root: %SHARD_ROOT%
echo Backend: http://127.0.0.1:8001
echo Frontend: http://127.0.0.1:3000
echo Profile: portable
echo.
endlocal
