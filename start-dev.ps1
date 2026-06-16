# ProductHub dev environment - one-click startup
# Order: Docker engine -> Postgres container (wait healthy) -> backend uvicorn:8000 -> frontend vite:5273
# Idempotent: skips whatever is already running. Backend/frontend each open their own window (close window = stop).
# ASCII-only on purpose: avoids PowerShell 5.1 / GBK encoding breakage on zh-CN Windows.
# Usage:  .\start-dev.ps1     (if blocked once:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned)

$root      = $PSScriptRoot
$backend   = Join-Path $root 'backend'
$frontend  = Join-Path $root 'frontend'
$venvPy    = Join-Path $backend '.venv\Scripts\python.exe'
$container = 'producthub-dev-pg'
$dockerApp = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'

function Test-Port([int]$port) {
  $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
function Docker-Ready {
  docker ps 2>$null | Out-Null
  return ($LASTEXITCODE -eq 0)
}

Write-Host ""
Write-Host "=== ProductHub dev startup ===" -ForegroundColor Cyan

# 1) Docker engine
Write-Host "[1/4] Docker engine..." -ForegroundColor Yellow
if (-not (Docker-Ready)) {
  if (Test-Path $dockerApp) {
    Write-Host "      engine down; launching Docker Desktop (first start 30-90s)..."
    Start-Process $dockerApp | Out-Null
  } else {
    Write-Host "      Docker Desktop not found at $dockerApp - start Docker manually, then rerun." -ForegroundColor Red
  }
  $ok = $false
  for ($i = 1; $i -le 40; $i++) {
    Start-Sleep 5
    if (Docker-Ready) { $ok = $true; break }
    Write-Host ("      waiting for engine... {0}s" -f ($i * 5))
  }
  if (-not $ok) { Write-Host "Docker engine not ready after 200s. Aborting." -ForegroundColor Red; exit 1 }
}
Write-Host "      engine ready [OK]" -ForegroundColor Green

# 2) Postgres container
Write-Host "[2/4] Postgres container $container ..." -ForegroundColor Yellow
$exists = docker ps -a --filter ("name=^{0}$" -f $container) --format '{{.Names}}' 2>$null
if (-not $exists) {
  Write-Host "      container $container not found. Create the dev DB (port 5440) first." -ForegroundColor Red
  exit 1
}
docker start $container 2>$null | Out-Null
$health = ''
for ($i = 1; $i -le 30; $i++) {
  $health = docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' $container 2>$null
  if ($health -eq 'healthy' -or $health -eq 'running') { break }
  Start-Sleep 2
}
Write-Host "      Postgres: $health [OK]" -ForegroundColor Green

# 3) backend (uvicorn :8000) in its own window
Write-Host "[3/4] backend (uvicorn :8000) ..." -ForegroundColor Yellow
if (Test-Port 8000) {
  Write-Host "      :8000 already listening, skip [OK]" -ForegroundColor Green
} elseif (-not (Test-Path $venvPy)) {
  Write-Host "      venv not found: $venvPy - create it and install deps first." -ForegroundColor Red
} else {
  $cmd = "Set-Location '$backend'; `$env:PYTHONUTF8='1'; `$env:PYTHONIOENCODING='utf-8'; & '$venvPy' -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
  Start-Process powershell -ArgumentList '-NoExit', '-Command', $cmd | Out-Null
  Write-Host "      backend window launched [OK]" -ForegroundColor Green
}

# 4) frontend (vite :5273) in its own window
Write-Host "[4/4] frontend (vite :5273) ..." -ForegroundColor Yellow
if (Test-Port 5273) {
  Write-Host "      :5273 already listening, skip [OK]" -ForegroundColor Green
} else {
  $cmd = "Set-Location '$frontend'; npm run dev"
  Start-Process powershell -ArgumentList '-NoExit', '-Command', $cmd | Out-Null
  Write-Host "      frontend window launched [OK]" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== all set ===" -ForegroundColor Cyan
Write-Host "  Frontend:  http://localhost:5273"
Write-Host "  Backend:   http://localhost:8000/docs"
Write-Host "  Database:  localhost:5440  (container $container)"
Write-Host "Backend/frontend run in separate windows; close a window to stop it. Safe to re-run."
Write-Host ""
