@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Action Start
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
