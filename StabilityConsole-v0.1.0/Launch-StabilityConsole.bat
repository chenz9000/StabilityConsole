@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 launch.py %*
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo FAIL: Python 3.10+ is required. Install from python.org with Tkinter support.
    pause
    exit /b 2
  )
  python launch.py %*
)
if errorlevel 1 (
  echo.
  echo FAILED: Stability Console did not exit successfully.
  echo Review %%LOCALAPPDATA%%\StabilityConsole\stability.log if present.
  pause
  exit /b 1
)
endlocal

