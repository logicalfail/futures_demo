@echo off
setlocal enabledelayedexpansion

REM Futures Terminal launcher
REM Port/host from server_config.yaml, overridable via args

set ROOT_DIR=%~dp0
set ROOT_DIR=%ROOT_DIR:~0,-1%
set PYTHONPATH=%ROOT_DIR%

REM --- Read port and host from server_config.yaml ---
set HOST=127.0.0.1
set PORT=8000

if exist "%ROOT_DIR%\server_config.yaml" (
    for /f "tokens=*" %%a in ('python -c "import yaml; c=yaml.safe_load(open(r'%ROOT_DIR%/server_config.yaml', encoding='utf-8')); print(c['server'].get('port', 8000))" 2^>nul') do set PORT=%%a
    for /f "tokens=*" %%a in ('python -c "import yaml; c=yaml.safe_load(open(r'%ROOT_DIR%/server_config.yaml', encoding='utf-8')); print(c['server'].get('host', '127.0.0.1'))" 2^>nul') do set HOST=%%a
)

REM CLI args override
if not "%1"=="" set PORT=%1
if not "%2"=="" set HOST=%2

echo.
echo ============================================
echo   Futures Terminal
echo   http://%HOST%:%PORT%
echo   Config: %ROOT_DIR%\server_config.yaml
echo ============================================
echo.

if not exist "%ROOT_DIR%\frontend\dist\index.html" (
    echo [..] Building frontend^...
    pushd "%ROOT_DIR%\frontend"
    if !errorlevel! neq 0 (
        echo [FAIL] Cannot find frontend directory at "%ROOT_DIR%\frontend"
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

echo [..] Starting server at http://%HOST%:%PORT%
echo.

python -m uvicorn server.app:create_app --host %HOST% --port %PORT% --factory --log-level info

if errorlevel 1 (
    echo [FAIL] Start failed. Check: port %PORT% in use? pip install -r requirements.txt?
    pause
)
