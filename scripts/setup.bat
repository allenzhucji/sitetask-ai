@echo off
setlocal

set "ROOT=%~dp0.."
pushd "%ROOT%" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python 3.12 virtual environment...
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python launcher was not found. Install Python 3.12 or newer.
        popd
        exit /b 1
    )
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        popd
        exit /b 1
    )
)

set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :failed

"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo SiteTask AI development environment is ready.
popd
exit /b 0

:failed
echo Dependency installation failed.
popd
exit /b 1
