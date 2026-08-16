@echo off
setlocal

echo [J-CLOUD] Stopping local shard processes...

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8001 .*LISTENING"') do taskkill /PID %%P /T /F >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":3000 .*LISTENING"') do taskkill /PID %%P /T /F >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8080 .*LISTENING"') do taskkill /PID %%P /T /F >nul 2>&1

echo [J-CLOUD] Local shard stopped.
endlocal
