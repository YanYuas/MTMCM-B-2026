$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$cf = Join-Path $PSScriptRoot 'tools\cloudflared.exe'
if (-not (Test-Path $cf)) {
  Write-Host '未找到 tools\cloudflared.exe；请下载 cloudflared 或 winget install Cloudflare.cloudflared'
  exit 1
}
Write-Host '确保本地 8765 已启动，然后复制输出中的 https://...trycloudflare.com'
& $cf tunnel --url 'http://127.0.0.1:8765' --no-autoupdate
