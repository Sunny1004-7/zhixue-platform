param(
  [int]$BackendPort = 8111,
  [int]$FrontendPort = 5191
)

$frontendRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendRoot = (Resolve-Path (Join-Path $frontendRoot '..\backend')).Path
$runId = [guid]::NewGuid().ToString('N')
$dbPath = Join-Path $backendRoot ('.data\a1_a2_qa_clean_' + $runId + '.db')
$backendOut = Join-Path $backendRoot ('.data\a1_a2_qa_backend_' + $runId + '.stdout.log')
$backendErr = Join-Path $backendRoot ('.data\a1_a2_qa_backend_' + $runId + '.stderr.log')
$frontendOut = Join-Path $frontendRoot ('a1_a2_qa_frontend_' + $runId + '.stdout.log')
$frontendErr = Join-Path $frontendRoot ('a1_a2_qa_frontend_' + $runId + '.stderr.log')
$occupied = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -in $BackendPort,$FrontendPort }
if ($occupied) { throw "clean A1/A2 QA ports are already in use: $($occupied.LocalPort -join ',')" }

$oldDb = $env:ZHIXING_DATABASE_URL
$oldCors = $env:ZHIXING_CORS_ORIGINS
$oldApiBase = $env:VITE_API_BASE_URL
$oldQaBase = $env:A1_A2_BASE_URL
$oldQaApi = $env:A1_A2_API_BASE
$env:ZHIXING_DATABASE_URL = 'sqlite:///' + ($dbPath -replace '\\','/')
$env:ZHIXING_CORS_ORIGINS = "http://127.0.0.1:$FrontendPort"
$env:VITE_API_BASE_URL = "http://127.0.0.1:$BackendPort/api/v1"
$env:A1_A2_BASE_URL = "http://127.0.0.1:$FrontendPort"
$env:A1_A2_API_BASE = "http://127.0.0.1:$BackendPort/api/v1"

$backend = $null
$frontend = $null
try {
  Push-Location $backendRoot
  try {
    & python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "clean SQLite migration failed with code $LASTEXITCODE" }
  }
  finally {
    Pop-Location
  }

  $backend = Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port',$BackendPort `
    -WorkingDirectory $backendRoot -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr
  $frontend = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--host','127.0.0.1','--port',$FrontendPort `
    -WorkingDirectory $frontendRoot -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr

  $ready = $false
  for ($i = 0; $i -lt 80; $i++) {
    Start-Sleep -Milliseconds 500
    try {
      $apiReady = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$BackendPort/api/v1/health" -TimeoutSec 2).StatusCode -eq 200
      $uiReady = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$FrontendPort/login" -TimeoutSec 2).StatusCode -eq 200
      if ($apiReady -and $uiReady) { $ready = $true; break }
    }
    catch {
      if (($backend -and $backend.HasExited) -or ($frontend -and $frontend.HasExited)) { break }
    }
  }
  if (-not $ready) { throw 'clean A1/A2 QA servers did not become ready' }

  Push-Location $frontendRoot
  try {
    & node qa/verify-a1-a2.cjs
    if ($LASTEXITCODE -ne 0) { throw "A1/A2 Playwright exited with code $LASTEXITCODE" }
  }
  finally {
    Pop-Location
  }
  Write-Output "A1/A2 clean SQLite evidence database: $dbPath"
}
finally {
  if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
  if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
  $childIds = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $BackendPort,$FrontendPort } |
    Select-Object -ExpandProperty OwningProcess -Unique
  if ($childIds) { Stop-Process -Id $childIds -Force -ErrorAction SilentlyContinue }
  if ($null -ne $oldDb) { $env:ZHIXING_DATABASE_URL = $oldDb } else { Remove-Item Env:ZHIXING_DATABASE_URL -ErrorAction SilentlyContinue }
  if ($null -ne $oldCors) { $env:ZHIXING_CORS_ORIGINS = $oldCors } else { Remove-Item Env:ZHIXING_CORS_ORIGINS -ErrorAction SilentlyContinue }
  if ($null -ne $oldApiBase) { $env:VITE_API_BASE_URL = $oldApiBase } else { Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue }
  if ($null -ne $oldQaBase) { $env:A1_A2_BASE_URL = $oldQaBase } else { Remove-Item Env:A1_A2_BASE_URL -ErrorAction SilentlyContinue }
  if ($null -ne $oldQaApi) { $env:A1_A2_API_BASE = $oldQaApi } else { Remove-Item Env:A1_A2_API_BASE -ErrorAction SilentlyContinue }
}
