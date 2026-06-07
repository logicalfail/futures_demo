@echo off
setlocal enabledelayedexpansion

REM Futures Terminal - Background Launcher
REM Starts server in background, opens browser, bat exits.
REM Usage: start_bg.bat [port] [host]

set ROOT_DIR=%~dp0
set ROOT_DIR=%ROOT_DIR:~0,-1%
set PYTHONPATH=%ROOT_DIR%

REM --- Read config ---
set HOST=127.0.0.1
set PORT=8000

if exist "%ROOT_DIR%\server_config.yaml" (
    for /f "tokens=*" %%a in ('python -c "import yaml; c=yaml.safe_load(open(r'%ROOT_DIR%/server_config.yaml', encoding='utf-8')); print(c['server'].get('port', 8000))" 2^>nul') do set PORT=%%a
    for /f "tokens=*" %%a in ('python -c "import yaml; c=yaml.safe_load(open(r'%ROOT_DIR%/server_config.yaml', encoding='utf-8')); print(c['server'].get('host', '127.0.0.1'))" 2^>nul') do set HOST=%%a
)

REM CLI overrides
if not "%1"=="" set PORT=%1
if not "%2"=="" set HOST=%2

echo.
echo ============================================
echo   Futures Terminal (Background)
echo   http://%HOST%:%PORT%
echo ============================================
echo.

REM --- Build frontend if needed ---
if not exist "%ROOT_DIR%\frontend\dist\index.html" (
    echo [..] Building frontend...
    pushd "%ROOT_DIR%\frontend"
    if !errorlevel! neq 0 (
        echo [FAIL] Cannot find frontend directory
        pause
        exit /b 1
    )
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

REM --- Kill existing instance on same port ---
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /c":%PORT% "') do (
    if not "%%a"=="0" (
        echo [..] Stopping existing process on port %PORT% (PID %%a)...
        taskkill /PID %%a /f >nul 2>&1
        timeout /t 2 /nobreak >nul
    )
)

REM --- Start server in background ---
echo [..] Starting server at http://%HOST%:%PORT%
start /B "" python -m uvicorn server.app:create_app --host %HOST% --port %PORT% --factory --log-level info > "%ROOT_DIR%\server.log" 2>&1

REM --- Wait a moment then verify ---
timeout /t 2 /nobreak >nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /c":%PORT% "') do (
    echo [OK] Server started successfully (PID %%a)
    echo.
    echo   Open: http://%HOST%:%PORT%
    echo   Log:  %ROOT_DIR%\server.log
    echo   Stop: taskkill /PID %%a
    echo.
    REM Open browser
    start http://%HOST%:%PORT%
    goto :done
)

echo [FAIL] Server failed to start on port %PORT%. Check server.log
pause
exit /b 1

:done
echo [OK] Background launcher complete. Close this window safely.
