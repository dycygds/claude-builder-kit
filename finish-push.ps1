# finish-push.ps1 — 用 Git Credential Manager 里已登录的账号完成建仓 + 推送。
#
# 前提：已经跑过  git-credential-manager github login  并在浏览器里授权成功。
# 用法：powershell -ExecutionPolicy Bypass -File .\finish-push.ps1
#
# 它做的事：从 GCM 取出已保存的 GitHub 凭据（不再弹窗）→ 交给 push.ps1 →
# 建仓 / 设 topics / 推送 main。token 只存在于本进程环境变量里。

$ErrorActionPreference = 'Stop'

$kitRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$gcm = @(
    "$env:ProgramFiles\Git\ucrt64\bin\git-credential-manager.exe",
    "$env:ProgramFiles\Git\mingw64\bin\git-credential-manager.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $gcm) { Write-Host 'git-credential-manager.exe not found.' -ForegroundColor Red; exit 1 }

# 先看看现在有没有已登录账号，避免再弹一次授权窗
$accounts = & $gcm github list 2>&1
if (-not $accounts) {
    Write-Host 'GCM 里还没有已登录的 GitHub 账号，正在发起浏览器授权…' -ForegroundColor Yellow
    & $gcm github login
}

# 非交互取凭据（已登录时立即返回，不会卡住）
$env:GIT_TERMINAL_PROMPT = '0'
$raw = "protocol=https`nhost=github.com`n`n" | & $gcm get 2>&1

$user = ($raw | Where-Object { $_ -match '^username=' }) -replace '^username=', ''
$pass = ($raw | Where-Object { $_ -match '^password=' }) -replace '^password=', ''

if (-not $pass) {
    Write-Host '取不到凭据：浏览器授权可能还没完成，或授权窗被关掉了。' -ForegroundColor Red
    Write-Host '重试：& "' + $gcm + '" github login'
    exit 1
}

Write-Host "已取得凭据：user=$user  token_len=$($pass.Length)" -ForegroundColor Green
$env:GITHUB_TOKEN = $pass

& powershell -ExecutionPolicy Bypass -File (Join-Path $kitRoot 'push.ps1')
exit $LASTEXITCODE
