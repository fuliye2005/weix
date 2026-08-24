@echo off
REM ============================================================
REM Weix - Windows 一键启动脚本
REM ============================================================
setlocal

REM 读取微信进程内存需要管理员权限；非管理员启动时自动请求 UAC 提升
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [权限] 正在请求管理员权限...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

echo ============================================================
echo  Weix - 启动服务 (Windows)
echo ============================================================

REM 切换到项目根目录
cd /d "%~dp0\.."
set "PROJECT_DIR=%CD%"
set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "PYTHONPATH=%BACKEND_DIR%;%PYTHONPATH%"
REM UIA/pywin32 必须使用同一个 Python 3.12 虚拟环境，禁止混用外部嵌入式 Python。
set "PYTHON_EXE=%PROJECT_DIR%\venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [错误] 未找到 Python 运行时，请先运行 scripts\setup.bat
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PYVER=%%v"
echo [启动] Python %PYVER%: %PYTHON_EXE%
"%PYTHON_EXE%" -c "from app.core.windows_runtime import assert_windows_runtime; assert_windows_runtime()"
if errorlevel 1 (
    echo [错误] Windows UIA 运行环境不安全，拒绝启动，避免跨 Python 版本加载 .pyd
    pause
    exit /b 1
)

echo [启动] FastAPI 后端 (端口 8000)...
start "Weix-Backend" /D "%BACKEND_DIR%" "%PYTHON_EXE%" -m app.main
timeout /t 3 /nobreak >nul

REM 启动前端
if exist "frontend\node_modules" (
    echo [启动] 前端开发服务器 (端口 5173)...
    start "Weix-Frontend" /D "%PROJECT_DIR%\frontend" cmd /c npm run dev -- --host 127.0.0.1
)

echo.
echo ============================================================
echo  Weix 服务已启动
echo   后端: http://localhost:8000
echo   后端文档: http://localhost:8000/docs
echo   前端: http://localhost:5173
echo.
echo   关闭窗口停止服务
echo ============================================================

REM 保持窗口打开
pause
