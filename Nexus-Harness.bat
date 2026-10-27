@echo off
rem ===========================================================================================
rem  Nexus-Harness v1.0.0 — lanzador.
rem
rem  Sin argumentos: abre la APP NATIVA de escritorio (ventana Tauri con su icono). Nunca el
rem  navegador: eso es una decision del operador, no del lanzador.
rem  Con --web:       arranca el motor y abre la interfaz en el navegador (a proposito).
rem  Con otro argumento: lo pasa al CLI (run / gate / selftest / models / lint / bridge).
rem ===========================================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
set "PYTHON=python"
set "PORT=8765"

rem --- 1) Cualquier motor huerfano en el puerto se va antes de arrancar -----------------------
rem  Un motor que sobrevivio a su ventana deja el puerto cogido y el .exe bloqueado: la app nueva
rem  no podria ni escuchar ni reemplazarlo. Se mata el ARBOL (taskkill /T), no solo el bootloader.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT%" ^| findstr LISTENING') do (
  if not "%%p"=="0" (
    echo Nexus-Harness: cerrando un motor anterior en el puerto %PORT% ^(pid %%p^)…
    taskkill /F /T /PID %%p >nul 2>nul
  )
)

rem --- 2) Argumentos explicitos: CLI o navegador ----------------------------------------------
if /i "%~1"=="--web" goto :web
if not "%~1"=="" (
  where %PYTHON% >nul 2>nul || (
    echo Python no esta en el PATH. Instala Python 3.11+ o ajusta PYTHON en este .bat
    pause
    exit /b 1
  )
  %PYTHON% -m nexus_harness %*
  exit /b %ERRORLEVEL%
)

rem --- 3) Por defecto: la ventana nativa ------------------------------------------------------
set "DESKTOP=%LOCALAPPDATA%\Nexus Harness\nexus-harness-desktop.exe"
if not exist "%DESKTOP%" set "DESKTOP=%~dp0apps\desktop\src-tauri\target\release\nexus-harness-desktop.exe"
if not exist "%DESKTOP%" (
  echo.
  echo No encuentro la app de escritorio. Se instala con el instalador del producto:
  echo     dist\NexusHarness-Setup-1.0.0.exe
  echo o se construye desde el codigo:
  echo     cd apps\desktop ^&^& npm run build
  echo.
  echo Si lo que quieres es la interfaz en el NAVEGADOR, lanza:  Nexus-Harness.bat --web
  pause
  exit /b 1
)
echo Nexus-Harness: abriendo la app de escritorio…
start "" "%DESKTOP%"
exit /b 0

rem --- 4) El navegador, solo si se pide --------------------------------------------------------
:web
where %PYTHON% >nul 2>nul || (
  echo Python no esta en el PATH. Instala Python 3.11+ o ajusta PYTHON en este .bat
  pause
  exit /b 1
)
echo Nexus-Harness: arrancando el motor en http://127.0.0.1:%PORT% (modo navegador)
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:%PORT%"
%PYTHON% -m nexus_harness serve
exit /b %ERRORLEVEL%
