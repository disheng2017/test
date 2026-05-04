$ErrorActionPreference = "Stop"

Write-Host "Watching NVIDIA GPU usage. Press Ctrl+C to stop."
Write-Host ""

while ($true) {
    Clear-Host
    Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host ""
    nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv
    Write-Host ""
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
    Start-Sleep -Seconds 2
}
