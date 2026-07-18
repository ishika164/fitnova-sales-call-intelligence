$ErrorActionPreference = "Stop"

Write-Host "=== 1. Installing dependencies ===" -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host "=== 2. Checking environment ===" -ForegroundColor Cyan
if (-not $env:GROQ_API_KEY) {
    Write-Host "WARNING: GROQ_API_KEY not set. Get a free key: https://console.groq.com/keys" -ForegroundColor Yellow
    Write-Host '  $env:GROQ_API_KEY = "your_key_here"' -ForegroundColor Yellow
}

Write-Host "=== 3. Generating synthetic test calls (skips if already present) ===" -ForegroundColor Cyan
if (-not (Test-Path "data\raw_calls") -or (Get-ChildItem "data\raw_calls" -ErrorAction SilentlyContinue).Count -eq 0) {
    python src/generate_test_calls.py
} else {
    Write-Host "  data/raw_calls already populated, skipping."
}

Write-Host "=== 4. Seeding org structure (idempotent) ===" -ForegroundColor Cyan
python -m src.seed

Write-Host "=== 5. Running the pipeline ===" -ForegroundColor Cyan
python -m src.pipeline

Write-Host "=== 6. Launching dashboard ===" -ForegroundColor Cyan
streamlit run dashboard/app.py