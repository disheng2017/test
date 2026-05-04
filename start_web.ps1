$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (!(Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating local virtual environment..."
    python -m venv .venv
}

Write-Host "Installing dependencies into .venv..."
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:FFMPEG_DIR = Join-Path $PSScriptRoot ".tools\ffmpeg\bin"
$nvidiaBins = @(
    ".\.venv\Lib\site-packages\nvidia\cublas\bin",
    ".\.venv\Lib\site-packages\nvidia\cudnn\bin",
    ".\.venv\Lib\site-packages\nvidia\cuda_nvrtc\bin"
) | ForEach-Object {
    $path = Join-Path $PSScriptRoot $_
    if (Test-Path $path) { (Resolve-Path $path).Path }
}
if ($nvidiaBins.Count -gt 0) {
    $env:PATH = ($nvidiaBins -join ";") + ";" + $env:PATH
    Write-Host "NVIDIA CUDA runtime paths added."
}
Write-Host ""
Write-Host "FFMPEG_DIR=$env:FFMPEG_DIR"
.\.venv\Scripts\python.exe -c "from video_commentary.ffmpeg import resolve_exe, require_ffmpeg; print('ffmpeg =', resolve_exe('ffmpeg')); print('ffprobe =', resolve_exe('ffprobe')); require_ffmpeg(); print('FFmpeg check ok')"

Write-Host ""
Write-Host "Starting web app at http://127.0.0.1:7860"
Write-Host "Keep this window open while using the browser."
Write-Host ""

.\.venv\Scripts\python.exe -m video_commentary web --host 127.0.0.1 --port 7860
