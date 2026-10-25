[CmdletBinding()]
param([switch]$NoBuild,[switch]$Practice)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$composePath = Join-Path $projectRoot 'real_records/compose.yaml'
$dockerCommand = 'docker'
$dockerPrefix = @()
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) { throw 'Install Docker Desktop or Docker Engine in Ubuntu-24.04 WSL first.' }
    $dockerCommand = 'wsl.exe'
    $dockerPrefix = @('-d','Ubuntu-24.04','-u','root','--exec','docker')
    # systemd services alone do not keep a WSL distro alive after a shell exits.
    $keepaliveFile = Join-Path $projectRoot 'output/real-wsl-keepalive.json'
    $keepalive = $null
    if (Test-Path -LiteralPath $keepaliveFile) {
        try {
            $savedKeepalive = Get-Content -LiteralPath $keepaliveFile -Raw | ConvertFrom-Json
            $candidateKeepalive = Get-Process -Id $savedKeepalive.pid -ErrorAction Stop
            if ($candidateKeepalive.ProcessName -eq 'wsl' -and $candidateKeepalive.StartTime.ToUniversalTime().Ticks -eq $savedKeepalive.started) { $keepalive = $candidateKeepalive }
        } catch { }
    }
    if (-not $keepalive) {
        New-Item -ItemType Directory -Path (Join-Path $projectRoot 'output') -Force | Out-Null
        $keepalive = Start-Process -FilePath wsl.exe -ArgumentList @('-d','Ubuntu-24.04','-u','root','--exec','sleep','infinity') -WindowStyle Hidden -PassThru
        @{pid=$keepalive.Id;started=$keepalive.StartTime.ToUniversalTime().Ticks} | ConvertTo-Json | Set-Content -LiteralPath $keepaliveFile
    }
    $windowsComposePath = $composePath.Replace('\','/')
    $composePath = (& wsl.exe -d Ubuntu-24.04 --exec wslpath -a $windowsComposePath).Trim()
    & wsl.exe -d Ubuntu-24.04 -u root --exec sh -lc 'if [ -f /var/lib/pulp-real-records.swap ]; then swapon /var/lib/pulp-real-records.swap 2>/dev/null || true; fi'
    & wsl.exe -d Ubuntu-24.04 -u root --exec /usr/sbin/service docker start
}
function Invoke-StackDocker { & $dockerCommand @dockerPrefix @args }
Invoke-StackDocker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and wait until its Linux engine is ready.' }
$testComposePath = $composePath.Substring(0,$composePath.Length-'compose.yaml'.Length)+'compose.test.yaml'
$practiceArgs = @('compose','-p','pulp-real-records-practice','-f',$composePath,'-f',$testComposePath)
if ($Practice) {
    Write-Host 'Starting the isolated practice workspace. Real-record containers pause to conserve RAM; all records are retained.'
    Invoke-StackDocker compose -f $composePath stop
    if ($LASTEXITCODE -ne 0) { throw 'Could not pause the real-record stack.' }
    $stackArgs = $practiceArgs
    $apiPort = 8020; $uiPort = 3020; $grafanaPort = 3021
} else {
    Invoke-StackDocker @practiceArgs stop
    if ($LASTEXITCODE -ne 0) { throw 'Could not pause the practice stack.' }
    $stackArgs = @('compose','-f',$composePath)
    $apiPort = 8010; $uiPort = 3010; $grafanaPort = 3011
}
Invoke-StackDocker @stackArgs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration validation failed.' }
$composeArgs = $stackArgs + @('up','-d')
if (-not $NoBuild) { $composeArgs += '--build' }
Invoke-StackDocker @composeArgs
if ($LASTEXITCODE -ne 0) { throw 'Service startup failed. Inspect docker compose -f real_records/compose.yaml logs.' }
Write-Host 'Waiting for the real-record API and dashboard...'
$ready = $false
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $apiHealth = Invoke-RestMethod "http://127.0.0.1:$apiPort/health" -TimeoutSec 3
        $uiHealth = Invoke-WebRequest "http://127.0.0.1:$uiPort/operations/real" -UseBasicParsing -TimeoutSec 3
        if ($apiHealth.status -eq 'ok' -and $uiHealth.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $ready) { throw 'Services are still starting. Inspect docker compose -f real_records/compose.yaml ps and logs.' }
if ($Practice) { Write-Host 'Ready: PRACTICE MODE. Upload the labeled files from data/real_records_practice.' }
else { Write-Host 'Ready: open Import real records at http://127.0.0.1:8765/operations' }
Write-Host "Dashboard: http://127.0.0.1:$uiPort/operations/real"
Write-Host 'Check System health in the dashboard for CDC, Flink and worker readiness.'
Write-Host "Grafana: http://127.0.0.1:$grafanaPort/d/real-records (admin / local-real-monitoring unless overridden)"
Write-Host 'No sample records were imported.'
