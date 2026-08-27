@echo off
setlocal enabledelayedexpansion
title Automated IT Systems Audit Tool - Shutdown
cd /d "%~dp0"

REM ===========================================================================
REM  Cleanly stop the backend and frontend.
REM
REM  PostgreSQL is deliberately LEFT RUNNING. It is a shared Windows service
REM  that other things on this machine may depend on, and it is not this
REM  application's to stop -- the app is a tenant of the database, not its
REM  owner.
REM
REM  Processes are located BY LISTENING PORT rather than by a PID file. A pid
REM  file goes stale the moment anything dies unexpectedly, and would then
REM  either kill nothing or, worse, kill whatever inherited the number. The
REM  port is the thing that actually matters here.
REM ===========================================================================

set "API_PORT=8000"
set "WEB_PORT=3000"
set "PG_SERVICE=postgresql-x64-17"

echo.
echo  ===============================================================
echo   Stopping the Automated IT Systems Audit Tool
echo  ===============================================================
echo.

set /a KILLED=0

call :stop_port %API_PORT% "API [uvicorn]"
call :stop_port %WEB_PORT% "Dashboard [next]"

REM --- confirm the ports are actually clear ---------------------------------
echo.
echo  Verifying...
ping -n 3 127.0.0.1 >nul

set "STILL="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%API_PORT% .*LISTENING"') do set "STILL=!STILL! %API_PORT%(pid %%P)"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%WEB_PORT% .*LISTENING"') do set "STILL=!STILL! %WEB_PORT%(pid %%P)"

if defined STILL (
    echo.
    echo   WARNING: still listening:!STILL!
    echo   Something did not shut down. Check Task Manager for stray
    echo   python.exe / node.exe processes.
    echo.
    pause
    exit /b 1
)

echo   Ports %API_PORT% and %WEB_PORT% are clear.

REM --- PostgreSQL is intentionally untouched --------------------------------
sc query "%PG_SERVICE%" 2>nul | find "RUNNING" >nul
if not errorlevel 1 (
    echo   PostgreSQL ^(%PG_SERVICE%^) left running - shared system service.
) else (
    echo   PostgreSQL ^(%PG_SERVICE%^) is not running - not started by this script.
)

echo.
if %KILLED% EQU 0 (
    echo   Nothing was running.
) else (
    echo   Stopped %KILLED% process tree^(s^).
)
echo.
REM  `ping -n` rather than `timeout /t`: timeout aborts with "Input redirection
REM  is not supported" whenever stdin is redirected, which happens if this is
REM  run from a script or a scheduled task rather than double-clicked.
ping -n 7 127.0.0.1 >nul
exit /b 0

REM ===========================================================================
:stop_port
set "PORT=%~1"
set "LABEL=%~2"
REM  NOTE: labels must not contain ( ) -- %LABEL% is expanded into a
REM  single-line `if ... echo`, and a literal ")" there closes the parser's
REM  block context, making the next word look like a command. That is exactly
REM  what "API (uvicorn)" did: cmd reported `on was unexpected at this time`.
REM  Square brackets are inert to the parser.
set "FOUND="
REM  netstat lists a port once per binding (IPv4 and IPv6), so the same PID can
REM  appear twice. Without the SEEN_ guard the script kills it, then tries again
REM  and reports "could not kill" for a process it just stopped itself -- noise
REM  that reads like a failure.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    if not defined SEEN_%%P (
    set "SEEN_%%P=1"
    set "FOUND=1"
    echo  Stopping %LABEL% on port %PORT% ^(PID %%P^)...
    REM /T kills the process tree: npm spawns node as a child, and killing only
    REM the parent would leave the actual server holding the port.
    taskkill /F /T /PID %%P >nul 2>&1
    if errorlevel 1 (
        echo        could not kill PID %%P - it may already have exited.
    ) else (
        set /a KILLED+=1
        echo        stopped.
    )
    )
)
if not defined FOUND echo  %LABEL% on port %PORT%: not running.
exit /b 0
