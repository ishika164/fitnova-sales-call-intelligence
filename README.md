# FitNova Sales-Call Intelligence — Prototype

A working, end-to-end pipeline: call audio in → transcription → diarization →
PII redaction → LLM scoring & issue-tagging → storage → role-based dashboard
with a contest/feedback loop.

See `system_design.md` for the architecture diagram and `WRITEUP.md` for the
full design rationale (rubric, tag taxonomy, edge cases, trade-offs, what I'd
build next).

## Tech stack

| Layer | Tool | Why |
|---|---|---|
| Language | Python 3.11 | |
| Transcription | faster-whisper (local, free) | No API cost, runs on CPU |
| Diarization | Pause-based heuristic with optional pyannote.audio integration for improved speaker separation | Free, works offline, with optional pyannote integration for improved speaker separation |
| LLM scoring & tagging | Groq API — Llama 3.3 70B (free tier) | Reliable structured JSON output, no cost |
| Database | SQLite + SQLAlchemy ORM | Zero setup, real relational schema |
| Dashboard | Streamlit | Fast to build 3 real role-based views |
| PII redaction | Python `re` (regex) | Deterministic, auditable, no LLM risk |
| Synthetic test audio | pyttsx3 + espeak-ng (offline TTS) | Free, no real call recordings existed to use |

## Dashboard

<img width="1920" height="915" alt="dashboard-sales-director" src="https://github.com/user-attachments/assets/60095a02-590e-451a-9f55-4fc706769a1c" />

<img width="1920" height="915" alt="dashboard-flag-grounding" src="https://github.com/user-attachments/assets/b2d87fb0-24d4-4e97-878c-aec08d052e42" />

<img width="1920" height="915" alt="dashboard-contest-flag" src="https://github.com/user-attachments/assets/c3a61c29-c505-41ed-a654-4e03a13bfeb2" />

## Troubleshooting for a fresh run

A few things a first-time evaluator is likely to hit — none of these are bugs,
they're normal one-time friction:

- **Windows: `.\run.ps1` fails with "running scripts is disabled on this system."**
  Run this once, then retry: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- **First run is slow / seems stuck at "Processing call...".** `faster-whisper`
  downloads a ~500MB model on its first run (cached afterwards). This is normal
  and can take a few minutes depending on your connection. If your network
  blocks `huggingface.co`, this step will fail — that's a network restriction,
  not a code issue.
- ****Scores may vary slightly between runs because LLM inference is probabilistic.**
  The overall evaluation remains consistent, with lower-quality calls receiving
  lower scores and more issue flags than well-handled calls.
- **`GROQ_API_KEY not set` error.** You need your own free key from
  console.groq.com/keys — see Setup above.

## Setup

Requires Python 3.10+ and `ffmpeg` (for audio processing) and `espeak-ng`
(only needed to regenerate the synthetic test calls; not needed if you
supply your own audio).

```bash
git clone <this repo>
cd fitnova

# 1. Get a free Groq API key (no credit card): https://console.groq.com/keys
export GROQ_API_KEY=your_key_here

# 2. (Optional) Get a free HuggingFace token for real diarization:
#    accept terms at https://huggingface.co/pyannote/speaker-diarization-3.1
#    then get a token at https://huggingface.co/settings/tokens
export HF_TOKEN=your_token_here
#    If you skip this, the pipeline automatically uses a pause-based
#    heuristic fallback instead of failing.

# 3. Run everything
./run.sh          # macOS/Linux
.\run.ps1         # Windows PowerShell
```

This installs dependencies, generates 3 synthetic test calls (if not already
present), seeds the org structure, runs the full pipeline on all calls, and
launches the dashboard at http://localhost:8501.

To re-run just the pipeline (e.g. after dropping new audio files into
`data/raw_calls/`):
```bash
python3 -m src.pipeline
```

## What's real vs mocked

| Component | Status | Notes |
|---|---|---|
| Ingestion adapter pattern | **Real** | `LocalFolderAdapter` is the one mocked *source* (stands in for a telephony/CRM API), but the adapter interface itself is real and swappable — adding a vendor means writing one class, not touching the pipeline. |
| Call audio | **Synthetic** | Generated with offline TTS (`src/generate_test_calls.py`) since no real FitNova recordings exist. Scripts are realistic dialogues written to deliberately include specific violations, so the analysis engine has real cases to catch. |
| Transcription | **Real** | `faster-whisper`, runs locally, no API cost. |
| Diarization | **Real, with documented fallback** | Diarization | **Real, with documented fallback — fallback confirmed firing in practice** | Primary: `pyannote.audio`. In actual testing, pyannote failed with a `torchaudio` version-compatibility error (`module 'torchaudio' has no attribute 'set_audio_backend'` — a known breaking change between recent torchaudio releases and pyannote's pinned dependency expectations). The pipeline caught this and fell back to the pause-based heuristic automatically, exactly as designed — this was observed live, not just anticipated. The dashboard now surfaces which method was used per call (`diarization_method` column) so a reviewer can see when flag timestamps came from the lower-confidence fallback. Fixing the pyannote/torchaudio version pin was out of scope for this submission window; noted as a follow-up. |
| PII redaction | **Real** | Regex-based, runs before storage. |
| Scoring & tagging | **Real** | Groq-hosted Llama 3.3 70B, free tier, JSON-schema-forced output. |
| Anti-hallucination grounding check | **Real, unit-tested** | See `tests/test_pipeline_run.py` and the walkthrough in `WRITEUP.md` — fabricated/invalid flags are provably dropped before they reach the DB. |
| Database & storage | **Real** | SQLite via SQLAlchemy, actual schema, actual writes, actual idempotency (proven by running the pipeline twice — second run shows all `SKIP`). |
| Dashboard | **Real** | Streamlit, 3 role views, live queries against the DB. |
| Feedback loop (contest a flag) | **Real** | Advisor can contest, Team Leader can resolve, both write back to the DB. |
| Retries on external calls | **Real** | Bounded retry + backoff around transcription and analysis calls; failures are isolated per-call and logged to `Call.processing_error`, not fatal to the batch. |

## Notes

This project uses external AI services (Groq API and optional Hugging Face models), so an internet connection and valid API keys are required for full functionality.

The complete pipeline—including ingestion, transcription, PII redaction, analysis, database storage, idempotent processing, dashboard, and feedback workflow—has been implemented. Unit tests are included for key pipeline components.

## Project structure

```
src/
  ingestion.py        # source-agnostic adapter pattern
  transcribe.py        # faster-whisper + pyannote/heuristic diarization
  pii_redaction.py      # regex-based PII redaction
  analysis.py           # scoring + tagging + anti-hallucination grounding
  models.py              # SQLAlchemy schema
  seed.py                  # org structure seeding
  pipeline.py               # orchestrator: ingest -> transcribe -> redact -> analyze -> store
  generate_test_calls.py     # synthetic call audio generator (mock data source)
dashboard/
  app.py                      # Streamlit — 3 role views + contest UI
tests/
  test_pipeline_run.py         # end-to-end pipeline test with mocked external calls
data/
  call_scripts.json             # ground-truth dialogue scripts for synthetic calls
  raw_calls/                     # generated audio (created by generate_test_calls.py)
system_design.md                  # architecture diagram
WRITEUP.md                         # full design writeup
```
