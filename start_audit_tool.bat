@echo off
setlocal enabledelayedexpansion
title Automated IT Systems Audit Tool - Launcher
cd /d "%~dp0"

REM ===========================================================================
REM  One-click launcher for the demo.
REM
REM  1. Ensure PostgreSQL's Windows service is running.
REM  2. Refuse to start if the ports are already taken -- if it is OUR tool
REM     already running, just open the browser instead of spawning duplicates.
REM  3. Start backend + frontend as separate background windows.
REM  4. POLL until both actually answer, then open the browser.
REM
REM  Nothing here sleeps a fixed number of seconds and hopes: every wait polls
REM  for a real response and gives up with a readable message on a cap.
REM ===========================================================================

set "PG_SERVICE=postgresql-x64-17"
set "API_PORT=8000"
set "WEB_PORT=3000"
set "URL=http://localhost:3000"
set "APIHEALTH=http://127.0.0.1:8000/api/health"
set "VENVPY=%~dp0venv\Scripts\python.exe"
set "CURL=%SystemRoot%\System32\curl.exe"

echo.
echo  ===============================================================
echo   Automated IT Systems Audit Tool
echo  ===============================================================
echo.

REM --- sanity: the project must actually be set up --------------------------
if not exist "%VENVPY%" (
    echo   ERROR: Python virtual environment not found at
    echo          %VENVPY%
    echo.
    echo   FIX: run this once, from this folder:
    echo          py -m venv venv
    echo          venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
if not exist "%~dp0.env" (
    echo   ERROR: .env not found. Copy .env.example to .env and fill it in
    echo          ^(SECRETS_KEY and DATABASE_URL^). See README.md section 2.
    echo.
    pause
    exit /b 1
)

REM --- make sure child processes can find node/npm and vagrant --------------
REM  Vagrant is needed for live SSH scans; node/npm for the frontend. Both are
REM  normally on PATH already, but a fresh double-click may not inherit a shell
REM  profile, so known install locations are appended defensively.
set "PATH=%PATH%;%ProgramFiles%\Vagrant\bin;%ProgramFiles%\Oracle\VirtualBox"
where npm >nul 2>&1
if errorlevel 1 (
    for /d %%D in ("%USERPROFILE%\nodejs\node-v*") do set "PATH=!PATH!;%%~fD"
)

REM ===========================================================================
REM  1. PostgreSQL service
REM ===========================================================================
echo  [1/4] PostgreSQL service ^(%PG_SERVICE%^)...
sc query "%PG_SERVICE%" 2>nul | find "RUNNING" >nul
if not errorlevel 1 (
    echo        already running.
    goto :pg_ok
)

sc query "%PG_SERVICE%" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ERROR: the service "%PG_SERVICE%" does not exist on this machine.
    echo   FIX:   install PostgreSQL 17, or edit PG_SERVICE at the top of this
    echo          file if your service has a different name ^(run: sc query state^= all ^| findstr /i postgres^)
    echo.
    pause
    exit /b 1
)

echo        not running - attempting to start it...
net start "%PG_SERVICE%" >nul 2>&1

REM  net start returns non-zero both for "access denied" and other failures,
REM  so the service state is re-checked rather than trusting the exit code.
sc query "%PG_SERVICE%" 2>nul | find "RUNNING" >nul
if errorlevel 1 (
    echo.
    echo   ERROR: could not start %PG_SERVICE% - this usually needs Administrator.
    echo   FIX:   press Win+R, type  services.msc  , find "%PG_SERVICE%", right-click it and choose Start. Then run this launcher again.
    echo.
    pause
    exit /b 1
)
echo        started.
:pg_ok

REM ===========================================================================
REM  2. Ports - do not spawn duplicates
REM ===========================================================================
echo  [2/4] Checking ports %API_PORT% and %WEB_PORT%...

set "API_BUSY="
set "WEB_BUSY="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%API_PORT% .*LISTENING"') do set "API_BUSY=%%P"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%WEB_PORT% .*LISTENING"') do set "WEB_BUSY=%%P"

if not defined API_BUSY if not defined WEB_BUSY (
    echo        both free.
    goto :launch
)

REM  Something is listening. Is it US, or an unrelated program?
"%CURL%" -s -o nul -m 3 "%APIHEALTH%"
if not errorlevel 1 (
    echo.
    echo   The audit tool appears to be running already.
    echo   Opening the browser instead of starting a second copy.
    echo.
    start "" "%URL%"
    echo   If you want a clean restart, run stop_audit_tool.bat first.
    echo.
    REM  `ping -n` rather than `timeout /t`: timeout aborts with "Input redirection
REM  is not supported" whenever stdin is redirected, which happens if this is
REM  run from a script or a scheduled task rather than double-clicked.
ping -n 7 127.0.0.1 >nul
    exit /b 0
)

echo.
echo   ERROR: port %API_PORT% and/or %WEB_PORT% is in use by something that is NOT
echo          this tool.
if defined API_BUSY echo          port %API_PORT% is held by PID %API_BUSY%
if defined WEB_BUSY echo          port %WEB_PORT% is held by PID %WEB_BUSY%
echo   FIX:   stop that program, or run stop_audit_tool.bat if it is a stale
echo          copy of this tool, then try again.
echo.
pause
exit /b 1

REM ===========================================================================
REM  3. Launch
REM ===========================================================================
:launch

REM  --- the frontend needs a production build before `npm run start` ---------
REM  BUILD_ID is the file `next start` actually checks for, and it is written
REM  LAST, so its presence means a build finished rather than merely started.
REM  Testing for the .next directory alone is not enough: an interrupted build
REM  leaves .next populated but with no BUILD_ID, and `next start` then dies
REM  with "Could not find a production build" -- which is exactly how this was
REM  found. A fresh clone has no .next at all and hits the same path.
if not exist "%~dp0frontend\node_modules" (
    echo  [3/4] Installing frontend dependencies ^(first run only, ~1 min^)...
    pushd "%~dp0frontend"
    call npm install --no-audit --no-fund
    popd
)
if not exist "%~dp0frontend\.next\BUILD_ID" (
    echo  [3/4] Building the dashboard ^(first run only, ~1 min^)...
    pushd "%~dp0frontend"
    call npm run build
    popd
    if not exist "%~dp0frontend\.next\BUILD_ID" (
        echo.
        echo   ERROR: the frontend build did not complete.
        echo   FIX:   run  cd frontend ^&^& npm install ^&^& npm run build  and read the output.
        echo.
        pause
        exit /b 1
    )
)

echo  [3/4] Starting backend and frontend...

REM  NOTE ON QUOTING -- this is fragile and was got wrong once, so it is spelled
REM  out. The repo path contains a space ("Audit Tool"), and the obvious form
REM      start "t" /min cmd /c "cd /d "%~dp0frontend" && npm run start"
REM  nests quotes inside an already-quoted cmd /c string. cmd mis-parses it and
REM  the frontend silently never starts, while the API does -- so the launcher
REM  looks half-broken for a reason that has nothing to do with either service.
REM
REM  Instead: `start /D` sets the working directory (quoted ONCE, by start
REM  itself), and the command that follows uses only relative paths, which
REM  contain no spaces and therefore need no quoting at all.
start "Audit Tool - API" /D "%~dp0" /min cmd /c venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port %API_PORT% --app-dir backend
start "Audit Tool - Web" /D "%~dp0frontend" /min cmd /c npm run start -- --port %WEB_PORT%

REM ===========================================================================
REM  4. Poll until both actually answer, then open the browser
REM ===========================================================================
echo  [4/4] Waiting for services to come up...

set /a TRIES=0
:wait_api
"%CURL%" -s -o nul -m 3 "%APIHEALTH%"
if not errorlevel 1 goto :api_up
set /a TRIES+=1
if !TRIES! GEQ 60 (
    echo.
    echo   ERROR: the API did not respond on port %API_PORT% within 60 seconds.
    echo   FIX:   look at the minimised "Audit Tool - API" window for the error.
    echo          A missing/incorrect DATABASE_URL in .env is the usual cause.
    echo.
    pause
    exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto :wait_api
:api_up
echo        API ready on port %API_PORT%.

set /a TRIES=0
:wait_web
"%CURL%" -s -o nul -m 3 "%URL%"
if not errorlevel 1 goto :web_up
set /a TRIES+=1
if !TRIES! GEQ 90 (
    echo.
    echo   ERROR: the dashboard did not respond on port %WEB_PORT% within 90 seconds.
    echo   FIX:   look at the minimised "Audit Tool - Web" window. If this is a
    echo          fresh clone, run:  cd frontend ^&^& npm install ^&^& npm run build
    echo.
    pause
    exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto :wait_web
:web_up
echo        Dashboard ready on port %WEB_PORT%.

echo.
echo  ===============================================================
echo   Ready. Opening %URL%
echo.
echo   Sign in with the account you created via bootstrap.py.
echo   To shut everything down, run stop_audit_tool.bat
echo  ===============================================================
echo.

start "" "%URL%"

ping -n 9 127.0.0.1 >nul
exit /b 0
