param([ValidateSet('Start','Stop','Status')][string]$Action='Start')
$ErrorActionPreference='Stop'
$env:PSModulePath=(Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/Modules')+';'+$env:PSModulePath
Import-Module Microsoft.PowerShell.Utility,Microsoft.PowerShell.Management,CimCmdlets,Microsoft.PowerShell.Archive -ErrorAction Stop
$ProgressPreference='SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$projectRoot=[IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$stateRoot=Join-Path $projectRoot '.launcher'
$logs=Join-Path $stateRoot 'logs'
$cache=Join-Path $projectRoot '.runtime/cache'
$stateFile=Join-Path $stateRoot 'services.json'
$powershell=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
New-Item -ItemType Directory -Force -Path $stateRoot,$logs,$cache | Out-Null
$logFile=Join-Path $logs 'launcher.log'
function Say([string]$Message){
  $line='['+(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')+'] '+$Message
  Write-Host $line
  Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}
function SaveJson($Object,[string]$Path){$Object | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Path -Encoding UTF8}
function ReadState{
  if(Test-Path -LiteralPath $stateFile){try{return Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json}catch{return $null}}
  return $null
}
function Owned($Service){
  if(!$Service){return $null}
  $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($Service.pid)" -ErrorAction SilentlyContinue
  if(!$p){return $null}
  $savedCreation=if(([string]$Service.created).StartsWith('utc:')){([string]$Service.created).Substring(4)}else{([datetime]$Service.created).ToUniversalTime().ToString('o')}
  if($p.CreationDate.ToUniversalTime().ToString('o') -ne $savedCreation){return $null}
  $expected=Join-Path $PSScriptRoot 'run-service.ps1'
  if(!$p.CommandLine -or !$p.CommandLine.Contains($expected) -or !$p.CommandLine.Contains($Service.run_id)){return $null}
  return $p
}
function StopOwned($State){
  if(!$State -or $State.root -ne $projectRoot){return}
  foreach($s in $State.services){
    $p=Owned $s
    if(!$p){continue}
    $tree=@($p);$cursor=0
    while($cursor -lt $tree.Count){
      $tree+=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($tree[$cursor].ProcessId)" -ErrorAction SilentlyContinue)
      $cursor++
    }
    [array]::Reverse($tree)
    foreach($item in $tree){
      $live=Get-CimInstance Win32_Process -Filter "ProcessId=$($item.ProcessId)" -ErrorAction SilentlyContinue
      if($live -and $live.CreationDate -eq $item.CreationDate){Stop-Process -Id $live.ProcessId -ErrorAction SilentlyContinue}
    }
  }
}
function Healthy([string]$Url){
  try{return (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200}catch{return $false}
}
function CachedDownload($Spec,[string]$Name){
  $file=Join-Path $cache $Name
  if(Test-Path -LiteralPath $file){
    if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Spec.sha256){return $file}
    throw "下载缓存校验失败：$Name。请将 .runtime/cache 中该文件移走后重新启动。"
  }
  Say "下载固定版本：$Name（首次准备）"
  $partial=$file+'.partial'
  Invoke-WebRequest -Uri $Spec.url -OutFile $partial -UseBasicParsing -TimeoutSec 180
  if((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Spec.sha256){throw "下载内容校验失败：$Name。未解压或执行该文件。"}
  Move-Item -LiteralPath $partial -Destination $file
  return $file
}
function RunChecked([string]$Exe,[string[]]$Arguments,[string]$Working,[string]$Log){
  Push-Location -LiteralPath $Working
  $previousPreference=$ErrorActionPreference
  try{
    $ErrorActionPreference='Continue'
    & $Exe @Arguments >> $Log 2>&1
    $ErrorActionPreference=$previousPreference
    if($LASTEXITCODE -ne 0){throw "命令执行失败（退出码$LASTEXITCODE），请查看：$Log"}
  }finally{$ErrorActionPreference=$previousPreference;Pop-Location}
}
function FreePort([int]$Start){
  foreach($port in $Start..($Start+50)){
    $socket=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$port)
    try{$socket.Start();return $port}catch{}finally{$socket.Stop()}
  }
  throw "端口$Start附近没有可用地址。请关闭不需要的本机服务后再试。"
}
function StartWorker([string]$Kind,[int]$Port,[int]$ApiPort,[string]$RunId){
  $worker=Join-Path $PSScriptRoot 'run-service.ps1'
  $arguments='-NoLogo -NoProfile -ExecutionPolicy Bypass -File "'+$worker+'" -Kind '+$Kind+' -Port '+$Port+' -ApiPort '+$ApiPort+' -RunId '+$RunId
  $p=Start-Process -FilePath $powershell -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs ($Kind+'.stdout.log')) -RedirectStandardError (Join-Path $logs ($Kind+'.stderr.log'))
  $info=Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)"
  return @{kind=$Kind;pid=$p.Id;created=('utc:'+$info.CreationDate.ToUniversalTime().ToString('o'));run_id=$RunId}
}
$lock=$null
try{
  for($attempt=0;$attempt -lt 720;$attempt++){
    try{$lock=[IO.File]::Open((Join-Path $stateRoot 'operation.lock'),'OpenOrCreate','ReadWrite','None');break}
    catch{
      if($attempt -eq 0){Say '等待本项目已有的准备或启动任务完成。'}
      Start-Sleep -Milliseconds 500
    }
  }
  if(!$lock){throw '已有启动任务仍在准备，请查看 .launcher/logs/launcher.log 后重试。'}
  $state=ReadState
  if($Action -eq 'Stop'){
    StopOwned $state
    if(Test-Path -LiteralPath $stateFile){Remove-Item -LiteralPath $stateFile}
    Say '本项目启动器创建的服务已停止，课程数据和配置已保留。';exit 0
  }
  if($Action -eq 'Status'){
    if($state){Say ("系统地址："+$state.frontend_url)}else{Say '本项目尚未启动。'}
    exit 0
  }
  Say '知学智教：检查运行环境。'
  if($state -and $state.root -eq $projectRoot -and @($state.services|Where-Object{!(Owned $_)}).Count -eq 0 -and (Healthy $state.health_url) -and (Healthy $state.frontend_url)){
    Say ('系统已在运行：'+$state.frontend_url);Start-Process $state.frontend_url;exit 0
  }
  StopOwned $state
  $spec=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtimes.json') -Raw | ConvertFrom-Json
  $pythonBase=Join-Path $projectRoot '.runtime/python-3.12.7'
  $python=Join-Path $pythonBase 'tools/python.exe'
  if(!(Test-Path -LiteralPath $python)){
    $zip=CachedDownload $spec.python 'python.3.12.7.zip'
    Expand-Archive -LiteralPath $zip -DestinationPath $pythonBase -Force
  }
  $actual=(& $python -c 'import platform;print(platform.python_version())').Trim()
  if($actual -ne $spec.python.version){throw 'Python运行时版本不匹配，请检查 .runtime/python-3.12.7。'}
  $node=$null
  # Stable Windows installation locations are independent of a terminal's temporary PATH.
  foreach($candidate in @((Join-Path $env:ProgramFiles 'nodejs/node.exe'),(Join-Path $projectRoot '.runtime/node-v20.18.0-win-x64/node.exe'))){
    if(Test-Path -LiteralPath $candidate){$v=(& $candidate --version).Trim();if($v -eq 'v20.18.0'){$node=$candidate;break}}
  }
  if(!$node){
    $zip=CachedDownload $spec.node 'node-v20.18.0-win-x64.zip'
    Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $projectRoot '.runtime') -Force
    $node=Join-Path $projectRoot '.runtime/node-v20.18.0-win-x64/node.exe'
  }
  $nodeDir=Split-Path -Parent $node
  $env:PATH=$nodeDir+';'+$env:PATH
  $env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8'
  $venv=Join-Path $projectRoot '.venv'
  $venvPython=Join-Path $venv 'Scripts/python.exe'
  if(!(Test-Path -LiteralPath $venvPython)){
    Say '创建项目Python虚拟环境。'
    RunChecked $python @('-m','venv',$venv) $projectRoot (Join-Path $logs 'prepare-python.log')
  }
  $venvVersion=(& $venvPython -c 'import platform;print(platform.python_version())').Trim()
  if($venvVersion -ne $spec.python.version){throw '已有.venv与Python 3.12.7不匹配。请先停止系统，将.venv移到备份目录后重新双击；backend/.data和.env应保留。'}
  $backend=Join-Path $projectRoot 'backend';$frontend=Join-Path $projectRoot 'frontend'
  $lockHash=(Get-FileHash -LiteralPath (Join-Path $backend 'requirements-complete.lock.txt')).Hash+':'+(Get-FileHash -LiteralPath (Join-Path $backend 'pyproject.toml')).Hash
  $pythonStamp=Join-Path $stateRoot 'python-dependencies.txt'
  if(!(Test-Path -LiteralPath $pythonStamp) -or (Get-Content -LiteralPath $pythonStamp -Raw).Trim() -ne $lockHash -or !(Test-Path -LiteralPath (Join-Path $venv 'Lib/site-packages/fastapi'))){
    Say '安装锁定的后端依赖，进度写入 .launcher/logs/prepare-python.log。'
    RunChecked $venvPython @('-m','pip','install','--disable-pip-version-check','--index-url','https://pypi.org/simple','-r','requirements-complete.lock.txt') $backend (Join-Path $logs 'prepare-python.log')
    RunChecked $venvPython @('-m','pip','install','--disable-pip-version-check','--index-url','https://pypi.org/simple','-e','.[dev]','--no-deps') $backend (Join-Path $logs 'prepare-python.log')
    Set-Content -LiteralPath $pythonStamp -Value $lockHash -Encoding ASCII
  }
  $npm=Join-Path $nodeDir 'node_modules/npm/bin/npm-cli.js'
  $npmHash=(Get-FileHash -LiteralPath (Join-Path $frontend 'package-lock.json')).Hash
  $npmStamp=Join-Path $stateRoot 'node-dependencies.txt'
  if(!(Test-Path -LiteralPath $npmStamp) -or (Get-Content -LiteralPath $npmStamp -Raw).Trim() -ne $npmHash -or !(Test-Path -LiteralPath (Join-Path $frontend 'node_modules/vite/bin/vite.js'))){
    Say '安装锁定的前端依赖，进度写入 .launcher/logs/prepare-node.log。'
    RunChecked $node @($npm,'ci','--no-audit','--no-fund') $frontend (Join-Path $logs 'prepare-node.log')
    Set-Content -LiteralPath $npmStamp -Value $npmHash -Encoding ASCII
  }
  $envFile=Join-Path $backend '.env'
  if(!(Test-Path -LiteralPath $envFile)){Copy-Item -LiteralPath (Join-Path $backend '.env.example') -Destination $envFile;Say '已创建 backend/.env，可在其中配置模型。'}
  Say '升级数据库，保留已有课程与学习记录。'
  New-Item -ItemType Directory -Force -Path (Join-Path $backend '.data') | Out-Null
  RunChecked $venvPython @('-m','dotenv','-f','.env','run','--',$venvPython,'-m','alembic','upgrade','head') $backend (Join-Path $logs 'migration.log')
  $apiPort=FreePort 8000;$frontPort=FreePort 5173
  SaveJson @{python=$venvPython;node=$node} (Join-Path $stateRoot 'runtime-paths.json')
  SaveJson @{backend=$apiPort;frontend=$frontPort} (Join-Path $stateRoot 'ports.json')
  $id=[guid]::NewGuid().ToString()
  $state=@{root=$projectRoot;run_id=$id;frontend_url="http://127.0.0.1:$frontPort/login";api_url="http://127.0.0.1:$apiPort/api/v1";health_url="http://127.0.0.1:$apiPort/api/v1/health";services=@()}
  $state.services+=StartWorker 'backend' $apiPort $apiPort $id
  SaveJson $state $stateFile
  $state.services+=StartWorker 'frontend' $frontPort $apiPort $id
  SaveJson $state $stateFile
  Say "等待后端端口${apiPort}与前端端口${frontPort}就绪。"
  $ready=$false
  for($i=0;$i -lt 90;$i++){
    if(@($state.services|Where-Object{!(Owned $_)}).Count -gt 0){throw '服务提前结束，请查看 .launcher/logs 中backend或frontend日志。'}
    if((Healthy $state.health_url) -and (Healthy $state.frontend_url)){$ready=$true;break}
    Start-Sleep -Milliseconds 600
  }
  if(!$ready){throw '服务未在等待窗口内就绪，请查看日志并检查 .env 数据库配置或本机端口。'}
  Say ('系统已就绪：'+$state.frontend_url)
  Start-Process $state.frontend_url
}catch{
  Say ('未能启动：'+$_.Exception.Message)
  Say ('日志目录：'+$logs)
  Say '网络失败可在网络恢复后重新双击；依赖失败请查看prepare日志；配置问题请核对backend/.env。'
  StopOwned (ReadState)
  exit 1
}finally{if($lock){$lock.Dispose()}}
