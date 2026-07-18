"""
Generates synthetic sales-call audio files for testing the pipeline.
Uses offline TTS (pyttsx3 + espeak-ng) so it costs nothing and needs no internet.

This is clearly a MOCK data source, standing in for real call recordings.
Real call audio would enter the pipeline the same way (see src/ingestion.py).
"""
import json
import os
import pyttsx3
from pydub import AudioSegment

SCRIPTS_PATH = "data/call_scripts.json"
OUT_DIR = "data/raw_calls"
TMP_DIR = "data/_tmp_tts"

VOICE_MAP = {
    "Advisor": {"voice": "gmw/en-us", "rate": 175},
    "Customer": {"voice": "gmw/en", "rate": 165},
}


def synth_line(text, speaker, out_path):
    # Re-init engine per line: reusing one pyttsx3/espeak engine across many
    # calls on Linux is flaky (driver silently drops later calls).
    import time
    for attempt in range(3):
        engine = pyttsx3.init()
        engine.setProperty("voice", VOICE_MAP[speaker]["voice"])
        engine.setProperty("rate", VOICE_MAP[speaker]["rate"])
        engine.save_to_file(text, out_path)
        engine.runAndWait()
        engine.stop()
        del engine
        if os.path.exists(out_path):
            return
        time.sleep(0.3)
    raise RuntimeError(f"TTS failed to produce {out_path} after retries")


def build_call(call_id, call_data):
    os.makedirs(TMP_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    combined = AudioSegment.silent(duration=400)
    gap = AudioSegment.silent(duration=350)

    for i, (speaker, text) in enumerate(call_data["lines"]):
        line_path = f"{TMP_DIR}/{call_id}_{i}.wav"
        synth_line(text, speaker, line_path)
        segment = AudioSegment.from_wav(line_path)
        combined += segment + gap

    out_path = f"{OUT_DIR}/{call_id}.wav"
    combined.export(out_path, format="wav")
    print(f"  -> {out_path} ({len(combined)/1000:.1f}s)")


def main():
    with open(SCRIPTS_PATH) as f:
        scripts = json.load(f)

    for call_id, call_data in scripts.items():
        print(f"Synthesizing {call_id}: {call_data['description']}")
        build_call(call_id, call_data)

    print("\nDone. Generated calls are in data/raw_calls/")


if __name__ == "__main__":
    main()
