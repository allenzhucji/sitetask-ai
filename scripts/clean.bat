@echo off
setlocal

set "ROOT=%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$root = [IO.Path]::GetFullPath('%ROOT%');" ^
    "foreach ($name in @('build', 'dist')) {" ^
    "  $target = [IO.Path]::GetFullPath((Join-Path $root $name));" ^
    "  if ([IO.Path]::GetDirectoryName($target) -ne $root) { throw 'Unsafe clean target.' };" ^
    "  if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force };" ^
    "}"

if errorlevel 1 (
    echo Clean failed.
    exit /b 1
)

echo Build and distribution directories were removed.
exit /b 0
