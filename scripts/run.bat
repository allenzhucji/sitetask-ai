@echo off
setlocal

set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Virtual environment not found. Run scripts\setup.bat first.
    exit /b 1
)

pushd "%ROOT%" || exit /b 1
"%PYTHON%" main.py
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%
