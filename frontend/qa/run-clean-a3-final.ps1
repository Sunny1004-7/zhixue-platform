param(
  [int]$BackendPort = 8107,
  [int]$FrontendPort = 5187
)

$backendRoot = (Resolve-Path '..\backend').Path
$dbName = 'a3_qa_clean_' + [guid]::NewGuid().ToString('N') + '.db'
$dbPath = Join-Path $backendRoot ('.data\' + $dbName)
$occupied = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $BackendPort,$FrontendPort }
if ($occupied) { throw "clean QA ports are already in use: $($occupied.LocalPort -join ',')" }
$oldDb = $env:ZHIXING_DATABASE_URL
$oldCors = $env:ZHIXING_CORS_ORIGINS
$env:ZHIXING_DATABASE_URL = 'sqlite:///' + ($dbPath -replace '\\','/')
$env:ZHIXING_CORS_ORIGINS = "http://127.0.0.1:$FrontendPort"
$backend = Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port',$BackendPort -WorkingDirectory $backendRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $backendRoot '.data\a3_qa_final_backend.stdout.log') -RedirectStandardError (Join-Path $backendRoot '.data\a3_qa_final_backend.stderr.log')
$env:VITE_API_BASE_URL = "http://127.0.0.1:$BackendPort/api/v1"
$frontendRoot = (Get-Location).Path
$frontend = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--host','127.0.0.1','--port',$FrontendPort -WorkingDirectory $frontendRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $frontendRoot 'a3_qa_final_frontend.stdout.log') -RedirectStandardError (Join-Path $frontendRoot 'a3_qa_final_frontend.stderr.log')
try {
  $ready = $false
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    $ports = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $BackendPort,$FrontendPort }
    if (($ports.LocalPort -contains $BackendPort) -and ($ports.LocalPort -contains $FrontendPort)) { $ready = $true; break }
  }
  if (-not $ready) { throw 'clean QA servers did not become ready' }
  $env:A3_BASE_URL = "http://127.0.0.1:$FrontendPort"
  node qa/verify-a3.cjs
  if ($LASTEXITCODE -ne 0) { throw "A3 Playwright exited with code $LASTEXITCODE" }
}
finally {
  if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
  if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
  $childIds = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $BackendPort,$FrontendPort } |
    Select-Object -ExpandProperty OwningProcess -Unique
  if ($childIds) { Stop-Process -Id $childIds -Force -ErrorAction SilentlyContinue }
  if ($oldDb) { $env:ZHIXING_DATABASE_URL = $oldDb } else { Remove-Item Env:ZHIXING_DATABASE_URL -ErrorAction SilentlyContinue }
  if ($oldCors) { $env:ZHIXING_CORS_ORIGINS = $oldCors } else { Remove-Item Env:ZHIXING_CORS_ORIGINS -ErrorAction SilentlyContinue }
  Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:A3_BASE_URL -ErrorAction SilentlyContinue
}
