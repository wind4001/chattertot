@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Action Doctor
set "result=%errorlevel%"
pause
exit /b %result%
