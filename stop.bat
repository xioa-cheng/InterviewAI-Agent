@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "DOCKER=C:\Users\lenovo\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
if not exist "%DOCKER%" set "DOCKER=docker"

echo ============================================
echo   InterviewAI  -  Stop
echo ============================================
echo.
echo Stopping services (data is kept)...
"%DOCKER%" compose down

echo.
echo   Done. All containers stopped. Your data is safe.
echo   (Start again anytime with start.bat)
echo.
pause
