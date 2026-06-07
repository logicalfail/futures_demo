@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ── 期货行情终端 ── 一键启动（Windows CMD 兼容） ──

set ROOT_DIR=%~dp0
set PYTHONPATH=%ROOT_DIR%

set HOST=127.0.0.1
set PORT=8000

echo.
echo ╔══════════════════════════════════════════╗
echo ║      期货行情终端  Futures Terminal       ║
echo ║      http://%HOST%:%PORT%              ║
echo ╚══════════════════════════════════════════╝
echo.

REM 检查前端构建
if not exist "%ROOT_DIR%frontend\dist\index.html" (
    echo [!] 前端尚未构建，正在构建...
    cd /d "%ROOT_DIR%frontend"
    call npm install >nul 2>&1
    call npm run build
    if !errorlevel! neq 0 (
        echo [FAIL] 前端构建失败
        pause
        exit /b 1
    )
    cd /d "%ROOT_DIR%"
    echo [✓] 前端构建完成
)

echo [+] 启动 FastAPI 服务 — http://%HOST%:%PORT%
echo     按 Ctrl+C 停止
echo.

python -m uvicorn server.app:create_app --host %HOST% --port %PORT% --factory --log-level info

if errorlevel 1 (
    echo.
    echo [FAIL] 启动失败。请确认:
    echo   - Python 已安装且可用
    echo   - 已安装依赖: pip install -r requirements.txt
    echo   - 端口 %PORT% 未被占用
    pause
)
