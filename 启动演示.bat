@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0启动演示.ps1" %*
if errorlevel 1 pause
