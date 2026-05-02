$ErrorActionPreference = "Continue"

$port = 7860
$env:FFMPEG_DIR = Join-Path $PSScriptRoot ".tools\ffmpeg\bin"

Write-Host "Project:" $PSScriptRoot
Write-Host "FFMPEG_DIR:" $env:FFMPEG_DIR
try {
    .\.venv\Scripts\python.exe -c "from video_commentary.ffmpeg import resolve_exe, require_ffmpeg; print('ffmpeg =', resolve_exe('ffmpeg')); print('ffprobe =', resolve_exe('ffprobe')); require_ffmpeg(); print('FFmpeg check ok')"
} catch {
    Write-Host "FFmpeg check failed:" $_.Exception.Message
}

$listener = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "Port $port is listening:"
    $listener | Select-Object LocalAddress,LocalPort,State,OwningProcess
} else {
    Write-Host "Port $port is not listening."
}

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port" -UseBasicParsing -TimeoutSec 5
    Write-Host "HTTP status:" $response.StatusCode
} catch {
    Write-Host "HTTP check failed:" $_.Exception.Message
}
