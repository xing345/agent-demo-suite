param([int]$Port = 8003)

# 双击即可：起服务 → 等就绪 → 自动打开浏览器 → 关窗口即停
# 参数 -Port 可换端口，例如：powershell -ExecutionPolicy Bypass -File 启动演示.ps1 -Port 813

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host ''
Write-Host '  Agent 运行时工程笔记 - 演示控制台' -ForegroundColor Cyan
Write-Host '  ----------------------------------' -ForegroundColor DarkGray

$python = Join-Path $here '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host '  [失败] 找不到虚拟环境 .venv\Scripts\python.exe' -ForegroundColor Red
    Write-Host '  请确认脚本放在 agent-demo-suite 根目录下。' -ForegroundColor Yellow
    Read-Host '  按回车关闭'
    exit 1
}

# 端口被占就直接复用，不重复启动
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host ("  [提示] 端口 {0} 已有服务在跑 (PID {1})，直接打开浏览器。" -f $Port, $busy.OwningProcess) -ForegroundColor Yellow
    Start-Process ("http://127.0.0.1:{0}" -f $Port)
    Write-Host '  这个窗口可以直接关掉，服务不受影响。' -ForegroundColor DarkGray
    Start-Sleep -Seconds 3
    exit 0
}

# .env 体检：没有模型配置会走降级，这里提前说清楚
$envFile = Join-Path $here '.env'
if (-not (Test-Path $envFile)) {
    Write-Host '  [注意] 没有找到 .env，服务会以离线降级模式启动（只生成 1 个任务）。' -ForegroundColor Yellow
} else {
    $provider = (Get-Content $envFile | Where-Object { $_ -match '^MODEL_PROVIDER=' } | Select-Object -First 1)
    if ($provider -match 'none' -or [string]::IsNullOrWhiteSpace($provider)) {
        Write-Host '  [注意] .env 里 MODEL_PROVIDER=none，会走降级模式。' -ForegroundColor Yellow
    }
}

$url = "http://127.0.0.1:{0}" -f $Port
Write-Host ("  启动服务: {0}" -f $url) -ForegroundColor DarkGray

# 后台等待服务就绪后自动开浏览器，避免打开空白页
$opener = @"
`$ok = `$false
for (`$i = 0; `$i -lt 90; `$i++) {
    try {
        `$r = Invoke-WebRequest -Uri 'http://127.0.0.1:$Port/console/api/config' -UseBasicParsing -TimeoutSec 2
        if (`$r.StatusCode -eq 200) { `$ok = `$true; break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (`$ok) { Start-Process 'http://127.0.0.1:$Port' } else { Write-Host '  [提示] 服务 45 秒内没就绪，请手动刷新浏览器。' -ForegroundColor Yellow }
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($opener))
Start-Process -FilePath 'powershell' -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', '-EncodedCommand', $encoded) -WindowStyle Hidden

Write-Host ''
Write-Host '  浏览器会自动打开。日志滚动起来就说明正常。' -ForegroundColor Green
Write-Host '  演示结束后按 Ctrl+C 或直接关掉这个窗口即可停止服务。' -ForegroundColor DarkGray
Write-Host ''

try {
    & $python -m uvicorn apps.console.main:app --host 127.0.0.1 --port $Port
} finally {
    Write-Host ''
    Write-Host '  服务已停止。' -ForegroundColor DarkGray
}