$ErrorActionPreference = "Continue"

$port = 7860
$listeners = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue

if (!$listeners) {
    Write-Host "No process is listening on port $port."
    exit 0
}

$pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pidValue in $pids) {
    try {
        $process = Get-Process -Id $pidValue -ErrorAction Stop
        Write-Host "Stopping process $pidValue ($($process.ProcessName)) on port $port..."
        Stop-Process -Id $pidValue -Force
    } catch {
        Write-Host "Failed to stop process $pidValue :" $_.Exception.Message
    }
}
