@echo off
setlocal

set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "OUTPUT=%ROOT%\dist\SiteTaskAI\SiteTaskAI.exe"

if not exist "%PYTHON%" (
    echo Virtual environment not found. Run scripts\setup.bat first.
    exit /b 1
)

pushd "%ROOT%" || exit /b 1

if /I "%~1"=="--check" (
    "%PYTHON%" -c "import PyInstaller, PySide6, dateparser, keyring, winotify, qfluentwidgets; from pathlib import Path; assert Path('main.py').is_file(); assert Path('app/resources/styles/dark.qss').is_file(); assert Path('app/resources/icons/sitetask-icon.ico').is_file(); print('Build prerequisites are ready.')"
    set "RESULT=%ERRORLEVEL%"
    popd
    exit /b %RESULT%
)

call scripts\test.bat
if errorlevel 1 (
    echo Tests failed. Packaging was cancelled.
    popd
    exit /b 1
)

"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --noupx ^
    --name SiteTaskAI ^
    --icon "%ROOT%\app\resources\icons\sitetask-icon.ico" ^
    --paths "%ROOT%" ^
    --distpath "%ROOT%\dist" ^
    --workpath "%ROOT%\build\work" ^
    --specpath "%ROOT%\build" ^
    --add-data "%ROOT%\app\resources;app\resources" ^
    --collect-data dateparser ^
    --collect-data qfluentwidgets ^
    --collect-submodules keyring.backends ^
    "%ROOT%\main.py"
if errorlevel 1 (
    echo PyInstaller build failed.
    popd
    exit /b 1
)

if not exist "%OUTPUT%" (
    echo Build completed without the expected executable: %OUTPUT%
    popd
    exit /b 1
)

"%PYTHON%" "%ROOT%\scripts\verify_bundle.py" "%ROOT%\dist\SiteTaskAI" --repair
if errorlevel 1 (
    echo Packaged Qt runtime validation failed.
    popd
    exit /b 1
)

echo Build completed: %OUTPUT%
popd
exit /b 0
