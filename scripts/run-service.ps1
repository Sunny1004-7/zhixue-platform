param(
  [Parameter(Mandatory=$true)][ValidateSet('backend','frontend')][string]$Kind,
  [Parameter(Mandatory=$true)][int]$Port,
  [Parameter(Mandatory=$true)][int]$ApiPort,
  [Parameter(Mandatory=$true)][string]$RunId
)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$stateRoot=Join-Path $projectRoot '.launcher'
$paths=Get-Content -LiteralPath (Join-Path $stateRoot 'runtime-paths.json') -Raw | ConvertFrom-Json
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
if($Kind -eq 'backend'){
  Set-Location -LiteralPath (Join-Path $projectRoot 'backend')
  $origins=@("http://127.0.0.1:$Port")
  # The chosen frontend port is supplied through the private runtime state.
  $ports=Get-Content -LiteralPath (Join-Path $stateRoot 'ports.json') -Raw | ConvertFrom-Json
  $env:ZHIXING_CORS_ORIGINS="http://127.0.0.1:$($ports.frontend),http://localhost:$($ports.frontend)"
  & $paths.python -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port $ApiPort
}else{
  Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
  $env:VITE_API_BASE_URL="http://127.0.0.1:$ApiPort/api/v1"
  & $paths.node (Join-Path $projectRoot 'frontend/node_modules/vite/bin/vite.js') --host 127.0.0.1 --port $Port --strictPort
}
exit $LASTEXITCODE
