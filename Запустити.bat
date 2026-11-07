@echo off
setlocal
cd /d "%~dp0"
title Slovoprostir - local platform

if exist ".venv\Scripts\python.exe" goto check_flask

echo Preparing Python environment...
if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" (
    "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" -m venv .venv
) else (
    py -m venv .venv
)
if errorlevel 1 goto setup_error

:check_flask
".venv\Scripts\python.exe" -c "import flask" >nul 2>&1
if not errorlevel 1 goto run
echo Installing required packages. Internet is needed for this first setup.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_error

:run
echo.
echo Platform address: http://127.0.0.1:5000
echo Keep this window open while using the platform.
echo Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" app.py --open-browser
if errorlevel 1 goto run_error
goto end

:setup_error
echo.
echo Setup failed. Check that Python 3.10 or newer is installed.
echo For manual setup, see README.md in this folder.
pause
goto end

:run_error
echo.
echo The server could not start. Copy the error shown above.
pause

:end
endlocal
