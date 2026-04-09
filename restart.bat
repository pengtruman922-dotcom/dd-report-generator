@echo off
chcp 65001 >nul
title DD Report Generator - Restart

set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo ========================================
echo   DD Report Generator - Restarting...
echo ========================================
echo.

REM Kill existing backend and frontend windows by title
echo [1/4] Stopping old processes...
taskkill /FI "WINDOWTITLE eq DD-Backend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq DD-Frontend*" /T /F >nul 2>&1
timeout /t 2 /nobreak >nul

REM Start backend
echo [2/4] Starting backend (FastAPI :8000) ...
start "DD-Backend" cmd /k "cd /d %~dp0backend && \"%PYTHON_EXE%\" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

REM Wait for backend to start
timeout /t 3 /nobreak >nul

REM Start frontend
echo [3/4] Starting frontend (Vite :5173) ...
start "DD-Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 4 /nobreak >nul
echo [4/4] Opening browser...
start http://localhost:5173

echo.
echo ========================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo   Close the two command windows to stop
echo ========================================
echo.
pause
