<#
.SYNOPSIS
  期货行情终端 — 一键启动脚本
.DESCRIPTION
  启动 FastAPI 后端（同时提供 REST API / WebSocket / 前端静态文件）
  支持 dev / prod 两种模式
.PARAMETER Mode
  prod  - 生产模式（默认，使用已构建的前端文件）
  dev   - 开发模式，前台启动 uvicorn（带 hot-reload）
  devbg - 开发模式，后台启动
.EXAMPLE
  .\start.ps1 prod       # 生产模式
  .\start.ps1 dev        # 开发模式（前台，hot-reload）
  .\start.ps1 devbg      # 开发模式（后台进程）
#>

param(
  [ValidateSet('prod', 'dev', 'devbg')]
  [string]$Mode = 'prod'
)

$RootDir = Split-Path -Parent $PSCommandPath
$env:PYTHONPATH = $RootDir

$HostAddr = '127.0.0.1'
$Port = 8000

# ANSI 颜色
$Green  = [char]0x1b + '[32m'
$Yellow = [char]0x1b + '[33m'
$Cyan   = [char]0x1b + '[36m'
$Reset  = [char]0x1b + '[0m'
$Bold   = [char]0x1b + '[1m'

function Print-Banner {
  Write-Host @"

${Bold}${Cyan}╔══════════════════════════════════════════╗
║      期货行情终端  Futures Terminal       ║
║      http://${HostAddr}:${Port}              ║
╚══════════════════════════════════════════╝${Reset}

"@
}

function Ensure-Frontend {
  $dist = Join-Path $RootDir 'frontend' 'dist'
  $index = Join-Path $dist 'index.html'
  if (-not (Test-Path $index)) {
    Write-Host "${Yellow}[!] 前端尚未构建，正在构建...${Reset}"
    Push-Location (Join-Path $RootDir 'frontend')
    npm install | Out-Null
    npm run build
    Pop-Location
    Write-Host "${Green}[✓] 前端构建完成${Reset}"
  }
}

# ── 入口 ────────────────────────────────────────────────
Print-Banner

switch ($Mode) {
  'prod' {
    Ensure-Frontend
    Write-Host "${Green}[+] 生产模式 — 启动 FastAPI 服务 ${Reset}"
    Write-Host "    ${Cyan}http://${HostAddr}:${Port}${Reset}"
    Write-Host "    ${Yellow}按 Ctrl+C 停止${Reset}`n"
    python -m uvicorn server.app:create_app --host $HostAddr --port $Port --factory --log-level info
  }

  'dev' {
    Write-Host "${Yellow}[+] 开发模式 — 启动 FastAPI (hot-reload)${Reset}"
    Write-Host "    前端开发服:  ${Cyan}cd frontend && npm run dev${Reset}"
    Write-Host "    API 服     : ${Cyan}http://${HostAddr}:${Port}${Reset}"
    Write-Host "    ${Yellow}按 Ctrl+C 停止${Reset}`n"
    python -m uvicorn server.app:create_app --host $HostAddr --port $Port --factory --reload --log-level debug
  }

  'devbg' {
    Ensure-Frontend
    Write-Host "${Green}[+] 开发模式 — 后台启动${Reset}"
    $logFile = Join-Path $RootDir 'server.log'
    $jobName = 'FuturesTerminal'
    
    # 停止旧实例
    Get-Job -Name $jobName -ErrorAction SilentlyContinue | Stop-Job | Remove-Job
    Get-Process -Name python* -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -match 'uvicorn.*server.app' } |
      Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Job -Name $jobName -ScriptBlock {
      param($r, $h, $p)
      $env:PYTHONPATH = $r
      python -m uvicorn server.app:create_app --host $h --port $p --factory --log-level info
    } -ArgumentList $RootDir, $HostAddr, $Port

    Write-Host "    服务已后台启动  ${Cyan}http://${HostAddr}:${Port}${Reset}"
    Write-Host "    日志: ${Yellow}(Get-Job -Name '$jobName' | Receive-Job)${Reset}"
    Write-Host "    停止: ${Yellow}Get-Job -Name '$jobName' | Stop-Job | Remove-Job${Reset}`n"
  }
}
