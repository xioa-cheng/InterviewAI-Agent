@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "DOCKER=C:\Users\lenovo\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
set "DOCKERDESKTOP=C:\Users\lenovo\AppData\Local\Programs\DockerDesktop\Docker Desktop.exe"
if not exist "%DOCKER%" set "DOCKER=docker"

echo ============================================
echo   InterviewAI  -  Start
echo ============================================
echo.

echo [1/3] Checking Docker Desktop...
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 goto ready

echo   Docker Desktop is not running. Starting it...
start "" "%DOCKERDESKTOP%"
call :wait_docker
if errorlevel 1 (
    echo   [ERROR] Docker Desktop failed to start. Start it manually, then re-run.
    pause
    exit /b 1
)

:ready
echo   Docker is ready.

echo.
echo [2/3] Starting services...
"%DOCKER%" compose up -d
if errorlevel 1 (
    echo   [ERROR] Failed to start. Check the messages above.
    pause
    exit /b 1
)

echo.
echo [3/3] Opening browser...
start "" http://localhost:5173

echo.
echo   Done!  Open  http://localhost:5173
echo   (if the page shows nothing, wait a few seconds and refresh)
echo.
pause
exit /b 0

:wait_docker
set /a tries=0
:wait_loop
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 exit /b 0
set /a tries+=1
if %tries% geq 40 exit /b 1
timeout /t 3 /nobreak >nul
goto wait_loop
