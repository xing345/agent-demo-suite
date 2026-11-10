$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$Port = 8765
Write-Host ''
Write-Host '  Agent 运行时 - 知识库检索控制台' -ForegroundColor Cyan
Write-Host '  --------------------------------' -ForegroundColor DarkGray
$python = Join-Path $here '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { Write-Host '  [失败] 找不到 .venv\Scripts\python.exe' -ForegroundColor Red; Read-Host '  按回车关闭'; exit 1 }
$kb = 'D:\x\personal-kb'
if (-not (Test-Path (Join-Path $kb '.venv\Scripts\python.exe'))) { Write-Host '  [失败] 找不到知识库项目 D:\x\personal-kb' -ForegroundColor Red; Read-Host '  按回车关闭'; exit 1 }
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host ("  [提示] 端口 {0} 已有服务 (PID {1})，直接打开浏览器。" -f $Port, $busy.OwningProcess) -ForegroundColor Yellow
    Start-Process ("http://127.0.0.1:{0}" -f $Port); Start-Sleep -Seconds 3; exit 0
}
Write-Host '  [注意] 首次启动要加载向量模型，可能需要 20 秒，请等浏览器自动打开。' -ForegroundColor Yellow
Write-Host '  [说明] 这里演示的是检索与问答，不依赖运行时是否在跑。' -ForegroundColor DarkGray
$opener = @"
`$ok = `$false
for (`$i = 0; `$i -lt 200; `$i++) {
    try { `$r = Invoke-WebRequest -Uri 'http://127.0.0.1:$Port/health' -UseBasicParsing -TimeoutSec 2; if (`$r.StatusCode -eq 200) { `$ok = `$true; break } } catch { }
    Start-Sleep -Milliseconds 500
}
if (`$ok) { Start-Process 'http://127.0.0.1:$Port' } else { Write-Host '  [提示] 100 秒内没就绪，请手动刷新。' -ForegroundColor Yellow }
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($opener))
Start-Process -FilePath 'powershell' -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-EncodedCommand',$encoded) -WindowStyle Hidden
Write-Host ''
Write-Host '  演示结束后按 Ctrl+C 或直接关掉这个窗口即可停止服务。' -ForegroundColor DarkGray
Write-Host ''
$kbPython = Join-Path $kb '.venv\Scripts\python.exe'
try { & $kbPython -m uvicorn src.console:app --host 127.0.0.1 --port $Port --app-dir $kb } finally { Write-Host ''; Write-Host '  服务已停止。' -ForegroundColor DarkGray }
