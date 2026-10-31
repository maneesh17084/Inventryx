@echo off
rem Double-click to start Inventryx. Keep this window open while you use the app; close it to stop.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 run.py %*) || (python run.py %*)
if errorlevel 1 (
  echo.
  echo Inventryx stopped with an error - see the message above.
  pause
)
