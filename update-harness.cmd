@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0.harness\scripts\update-harness.ps1" %*
exit /b %ERRORLEVEL%
