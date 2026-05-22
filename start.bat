@echo off
if /i "%~1"=="__backend__" goto :run_backend
if /i "%~1"=="__frontend__" goto :run_frontend

setlocal
chcp 65001 >nul
title DD Report Generator

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"

call :resolve_python || goto :error
call :resolve_npm || goto :error

echo ========================================
echo   DD Report Generator
echo ========================================
echo.
echo Python: %PYTHON_EXE%
echo NPM:    %NPM_CMD%
echo.

echo [1/2] Starting backend (FastAPI :8000) ...
start "DD-Backend" /D "%BACKEND_DIR%" "%ComSpec%" /k call "%~f0" __backend__

call :wait_for_port 8000 20 backend || goto :error

echo [2/2] Starting frontend (Vite :5173) ...
start "DD-Frontend" /D "%FRONTEND_DIR%" "%ComSpec%" /k call "%~f0" __frontend__

call :wait_for_port 5173 20 frontend || goto :error
echo.
echo Opening browser...
start "" http://localhost:5173

echo.
echo ========================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo   Close the two command windows to stop the app
echo ========================================
echo.
pause
exit /b 0

:run_backend
setlocal
chcp 65001 >nul
title DD-Backend
call :resolve_python || goto :launcher_error
cd /d "%~dp0backend"
echo [DD-Backend] Working directory: %CD%
"%PYTHON_EXE%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
goto :launcher_exit

:run_frontend
setlocal
chcp 65001 >nul
title DD-Frontend
call :resolve_npm || goto :launcher_error
cd /d "%~dp0frontend"
echo [DD-Frontend] Working directory: %CD%
call "%NPM_CMD%" run dev
goto :launcher_exit

:launcher_error
echo.
echo Startup command aborted.

:launcher_exit
set "EXIT_CODE=%errorlevel%"
echo.
echo Process exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%

:resolve_python
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if exist "%PYTHON_EXE%" exit /b 0
for /f "delims=" %%I in ('where python 2^>nul') do (
    echo %%~fI | find /i "WindowsApps" >nul
    if errorlevel 1 (
        set "PYTHON_EXE=%%~fI"
        exit /b 0
    )
)
echo [ERROR] Python executable not found. Install Python 3.11 or update start.bat.
exit /b 1

:resolve_npm
for /f "delims=" %%I in ('where npm.cmd 2^>nul') do (
    set "NPM_CMD=%%~fI"
    exit /b 0
)
echo [ERROR] npm.cmd not found. Install Node.js 18+ and ensure npm is on PATH.
exit /b 1

:wait_for_port
setlocal
set "PORT=%~1"
set "MAX_TRIES=%~2"
set "SERVICE=%~3"
for /l %%I in (1,1,%MAX_TRIES%) do (
    powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } exit 1" >nul 2>&1
    if not errorlevel 1 (
        endlocal & exit /b 0
    )
    timeout /t 1 /nobreak >nul
)
echo [ERROR] Timed out waiting for %SERVICE% on port %PORT%.
endlocal & exit /b 1

:error
echo.
echo Startup aborted.
pause
exit /b 1
