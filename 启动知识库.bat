@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0启动知识库.ps1" %*
if errorlevel 1 pause
