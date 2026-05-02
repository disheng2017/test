$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (!(Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating local virtual environment..."
    python -m venv .venv
}

Write-Host "Installing dependencies into .venv..."
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:FFMPEG_DIR = Join-Path $PSScriptRoot ".tools\ffmpeg\bin"
Write-Host ""
Write-Host "FFMPEG_DIR=$env:FFMPEG_DIR"
.\.venv\Scripts\python.exe -c "from video_commentary.ffmpeg import resolve_exe, require_ffmpeg; print('ffmpeg =', resolve_exe('ffmpeg')); print('ffprobe =', resolve_exe('ffprobe')); require_ffmpeg(); print('FFmpeg check ok')"

Write-Host ""
Write-Host "Starting web app at http://127.0.0.1:7860"
Write-Host "Keep this window open while using the browser."
Write-Host ""

.\.venv\Scripts\python.exe -m video_commentary web --host 127.0.0.1 --port 7860
