@echo off
setlocal enabledelayedexpansion

REM -- Futures Terminal launcher --

set ROOT_DIR=%~dp0
set ROOT_DIR=%ROOT_DIR:~0,-1%
set PYTHONPATH=%ROOT_DIR%
set HOST=127.0.0.1
set PORT=8000

echo.
echo ============================================
echo   Futures Terminal
echo   http://%HOST%:%PORT%
echo ============================================
echo.

if not exist "%ROOT_DIR%\frontend\dist\index.html" (
    echo [..] Building frontend...
    pushd "%ROOT_DIR%\frontend"
    if not exist "node_modules" (
        call npm install --no-fund --no-audit
    )
    call npm run build
    if !errorlevel! neq 0 (
        echo [FAIL] Frontend build failed
        pause
        exit /b 1
    )
    popd
)

echo [..] Starting server at http://%HOST%:%PORT%
echo.

python -m uvicorn server.app:create_app --host %HOST% --port %PORT% --factory --log-level info

if errorlevel 1 (
    echo [FAIL] Start failed. Check: port %PORT% in use? pip install -r requirements.txt?
    pause
)
