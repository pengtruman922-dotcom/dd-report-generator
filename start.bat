@echo off
chcp 65001 >nul
title 尽调报告生成器

echo ========================================
echo   尽调报告生成器 - DD Report Generator
echo ========================================
echo.

:: Start backend
echo [1/2] 启动后端 (FastAPI :8000) ...
start "DD-Backend" cmd /k "cd /d %~dp0backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

:: Wait a moment for backend to start
timeout /t 3 /nobreak >nul

:: Start frontend
echo [2/2] 启动前端 (Vite :5173) ...
start "DD-Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

:: Wait for frontend to be ready then open browser
timeout /t 4 /nobreak >nul
echo.
echo 正在打开浏览器...
start http://localhost:5173

echo.
echo ========================================
echo   后端: http://localhost:8000
echo   前端: http://localhost:5173
echo   关闭: 关闭两个弹出的命令行窗口即可
echo ========================================
echo.
pause
