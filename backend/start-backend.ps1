# ============================================================
#  ProductHub 后端 — 鲁棒手动启动脚本（Windows PowerShell 5.1+）
#  用法：在 PowerShell 里运行
#     powershell -ExecutionPolicy Bypass -File "D:\Desktop\Moore 工业智能\北京合胜\ProductHub 产品中台\backend\start-backend.ps1"
#  特点：自检/启动数据库容器、等待 healthy、清理 8000 端口残留、无 --reload（本机更稳）。
#  停止：在本窗口按 Ctrl+C。
# ============================================================
$ErrorActionPreference = 'Stop'

$Backend   = "D:\Desktop\Moore 工业智能\北京合胜\ProductHub 产品中台\backend"
$Py        = Join-Path $Backend ".venv\Scripts\python.exe"
$Port      = 8000
$Container = "producthub-dev-pg"

function Step($n, $msg) { Write-Host "[$n/4] $msg" -ForegroundColor Cyan }

# ---- 1) Docker 引擎是否就绪 ----
Step 1 "检查 Docker 引擎..."
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Docker 引擎未就绪。请先手动打开【Docker Desktop】，等它完全启动（鲸鱼图标稳定）后重跑本脚本。" -ForegroundColor Yellow
    exit 1
}
Write-Host "  ✓ Docker 引擎就绪" -ForegroundColor Green

# ---- 2) 启动数据库容器并等待 healthy ----
Step 2 "启动数据库容器 $Container 并等待 healthy..."
docker start $Container 2>$null | Out-Null
$healthy = $false
foreach ($i in 1..30) {
    $st = (docker inspect -f '{{.State.Health.Status}}' $Container 2>$null)
    if ($st -eq 'healthy') { $healthy = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $healthy) {
    Write-Host "  ✗ 数据库未变 healthy（30s 超时）。请到 Docker Desktop 检查 $Container。" -ForegroundColor Yellow
    exit 1
}
Write-Host "  ✓ 数据库 healthy（127.0.0.1:5440）" -ForegroundColor Green

# ---- 3) 释放 8000 端口上的旧后端（避免端口占用） ----
Step 3 "释放 $Port 端口上的旧后端进程（若有）..."
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop; Write-Host "  · 已结束旧进程 PID $($c.OwningProcess)" }
    catch { }
}
Write-Host "  ✓ 端口已就绪" -ForegroundColor Green

# ---- 4) 启动后端（无 --reload，本机更稳） ----
Step 4 "启动后端 http://127.0.0.1:$Port  （Ctrl+C 停止）"
Set-Location $Backend
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
& $Py -m uvicorn app.main:app --host 127.0.0.1 --port $Port
