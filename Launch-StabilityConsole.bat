@echo off
setlocal
call "%~dp0StabilityConsole-v0.1.0\Launch-StabilityConsole.bat" %*
exit /b %errorlevel%
