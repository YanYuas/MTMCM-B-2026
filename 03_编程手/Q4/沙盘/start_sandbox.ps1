$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host '启动 3D 沙盘：http://127.0.0.1:8765/'
Start-Process -FilePath 'python' -ArgumentList '-m','http.server','8765','--bind','127.0.0.1' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Start-Sleep -Seconds 1
Start-Process 'http://127.0.0.1:8765/'
