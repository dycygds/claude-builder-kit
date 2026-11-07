# push.ps1 — create dycygds/claude-builder-kit on GitHub and push main.
#
#   $env:GITHUB_TOKEN = "ghp_..."      # scope: repo  (see PUSH.md for a pre-filled link)
#   powershell -ExecutionPolicy Bypass -File .\push.ps1
#
# Optional knobs:
#   $env:REPO_NAME    (default: claude-builder-kit)
#   $env:REPO_PRIVATE (default: false)
#
# The token is used through a temporary HTTP header for the single push and is never
# written to .git/config, the remote URL, disk, or the console.

$ErrorActionPreference = 'Stop'

$kitRoot  = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoName = if ($env:REPO_NAME) { $env:REPO_NAME } else { 'claude-builder-kit' }
$private  = if ($env:REPO_PRIVATE) { $env:REPO_PRIVATE } else { 'false' }
$token    = $env:GITHUB_TOKEN

if (-not $token) {
    Write-Host "GITHUB_TOKEN is not set." -ForegroundColor Yellow
    Write-Host "Create one here (scope: repo): https://github.com/settings/tokens/new?scopes=repo,read:user"
    Write-Host 'Then: $env:GITHUB_TOKEN = "ghp_..." ; powershell -ExecutionPolicy Bypass -File .\push.ps1'
    exit 2
}

$headers = @{
    Authorization          = "token $token"
    Accept                 = 'application/vnd.github+json'
    'User-Agent'           = 'claude-builder-kit-push'
    'X-GitHub-Api-Version' = '2022-11-28'
}

# 1. who is this token?
try {
    $me = Invoke-RestMethod -Uri 'https://api.github.com/user' -Headers $headers -TimeoutSec 30
} catch {
    Write-Host "Token rejected by GitHub: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
$owner = $me.login
Write-Host "authenticated as: $owner" -ForegroundColor Green

# 2. create the repo if it does not exist
$fullName = "$owner/$repoName"
$exists = $true
try {
    Invoke-RestMethod -Uri "https://api.github.com/repos/$fullName" -Headers $headers -TimeoutSec 30 | Out-Null
    Write-Host "repo already exists: $fullName" -ForegroundColor Yellow
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 404) { $exists = $false } else { throw }
}

if (-not $exists) {
    $body = @{
        name        = $repoName
        description = 'Claude Code builder kit: destructive-command hook, changelog skill, PR reviewer, and a bounty scanner that checks whether a bounty can actually pay.'
        private     = ($private -eq 'true')
        has_issues  = $true
        has_wiki    = $false
        has_projects = $false
    } | ConvertTo-Json
    $repo = Invoke-RestMethod -Uri 'https://api.github.com/user/repos' -Headers $headers `
        -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 60
    Write-Host "created: $($repo.html_url)" -ForegroundColor Green
}

# 3. topics, so the repo is discoverable
try {
    $topicsBody = @{ names = @('claude-code', 'claude', 'ai-agents', 'devtools', 'hooks', 'bounty', 'python') } | ConvertTo-Json
    Invoke-RestMethod -Uri "https://api.github.com/repos/$fullName/topics" -Headers $headers `
        -Method Put -Body $topicsBody -ContentType 'application/json' -TimeoutSec 30 | Out-Null
    Write-Host 'topics set' -ForegroundColor Green
} catch {
    Write-Host "topics skipped: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 4. push main with a one-shot auth header (nothing persisted)
Push-Location $kitRoot
try {
    $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
    if ($branch -ne 'main') { & git branch -M main; $branch = 'main' }

    & git remote remove origin 2>$null
    & git remote add origin "https://github.com/$fullName.git"

    $basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$token"))
    & git -c http.extraheader="AUTHORIZATION: basic $basic" push -u origin $branch
    if ($LASTEXITCODE -ne 0) { throw "git push failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Host ''
Write-Host "pushed: https://github.com/$fullName" -ForegroundColor Green
Write-Host "next:   gh repo edit $fullName --add-topic claude-code,devtools   (optional)"
Write-Host "then:   open outreach/x-thread.md and post the thread"
