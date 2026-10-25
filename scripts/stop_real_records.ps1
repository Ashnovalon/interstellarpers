[CmdletBinding()]
param([switch]$Practice)
$ErrorActionPreference = 'Stop'
$composePath = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'real_records/compose.yaml'
if (Get-Command docker -ErrorAction SilentlyContinue) {
    if ($Practice) { & docker compose -p pulp-real-records-practice -f $composePath -f (Join-Path (Split-Path $composePath) 'compose.test.yaml') down }
    else { & docker compose -f $composePath down }
} else {
    $windowsComposePath = $composePath.Replace('\','/')
    $composePath = (& wsl.exe -d Ubuntu-24.04 --exec wslpath -a $windowsComposePath).Trim()
    if ($Practice) {
        $testComposePath = $composePath.Substring(0,$composePath.Length-'compose.yaml'.Length)+'compose.test.yaml'
        & wsl.exe -d Ubuntu-24.04 -u root --exec docker compose -p pulp-real-records-practice -f $composePath -f $testComposePath down
    } else { & wsl.exe -d Ubuntu-24.04 -u root --exec docker compose -f $composePath down }
}
if ($LASTEXITCODE -ne 0) { throw 'Could not stop real-record services.' }
$keepaliveFile = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'output/real-wsl-keepalive.json'
if (Test-Path -LiteralPath $keepaliveFile) {
    try {
        $savedKeepalive = Get-Content -LiteralPath $keepaliveFile -Raw | ConvertFrom-Json
        $candidateKeepalive = Get-Process -Id $savedKeepalive.pid -ErrorAction Stop
        if ($candidateKeepalive.ProcessName -eq 'wsl' -and $candidateKeepalive.StartTime.ToUniversalTime().Ticks -eq $savedKeepalive.started) { Stop-Process -Id $candidateKeepalive.Id }
    } catch { }
}
Write-Host 'Real-record services stopped. All persistent volumes are retained.'
