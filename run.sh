#!/bin/bash
# One-command demo runner. See README.md for what each step does and
# what is real vs mocked.
set -e

echo "=== 1. Installing dependencies ==="
pip install -r requirements.txt --break-system-packages

echo "=== 2. Checking environment ==="
if [ -z "$GROQ_API_KEY" ]; then
  echo "WARNING: GROQ_API_KEY not set. Get a free key: https://console.groq.com/keys"
  echo "  export GROQ_API_KEY=your_key_here"
  echo "The analysis step will fail without it."
fi

echo "=== 3. Generating synthetic test calls (skips if already present) ==="
if [ ! -d "data/raw_calls" ] || [ -z "$(ls -A data/raw_calls 2>/dev/null)" ]; then
  python3 src/generate_test_calls.py
else
  echo "  data/raw_calls already populated, skipping."
fi

echo "=== 4. Seeding org structure (idempotent) ==="
python3 -m src.seed

echo "=== 5. Running the pipeline (ingest -> transcribe -> redact -> analyze -> store) ==="
python3 -m src.pipeline

echo "=== 6. Launching dashboard ==="
echo "Opening at http://localhost:8501"
streamlit run dashboard/app.py
