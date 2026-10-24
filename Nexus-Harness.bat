@echo off
rem Nexus-Harness launcher. No arguments: starts the cockpit and opens it.
rem Any arguments: passes them to the CLI (run / gate / selftest / models / lint / bridge / relay).
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set "PYTHON=python"

where %PYTHON% >nul 2>nul || (
  echo Python no esta en el PATH. Instala Python 3.11+ o ajusta PYTHON en este .bat
  pause
  exit /b 1
)

if not "%~1"=="" (
  %PYTHON% -m nexus_harness %*
  exit /b %ERRORLEVEL%
)

echo Nexus-Harness: arrancando la cabina en http://127.0.0.1:8765
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8765"
%PYTHON% -m nexus_harness serve
