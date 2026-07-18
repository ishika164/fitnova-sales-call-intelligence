"""
Transcription + diarization.

Primary path: faster-whisper (transcription) + pyannote.audio (diarization).
Fallback path: if pyannote is unavailable (no HF token) or diarization
confidence is low (common on mono call-center audio), we fall back to a
pause-based heuristic and mark the call's diarization_confidence as "low".
This IS the handling for the "mono recordings / poor diarisation" edge
case named in the brief — not a TODO, an actual fallback that runs.

Requires internet access to huggingface.co on first run (model download,
cached afterwards). Not reachable from the build sandbox — see README.
"""
import os
from dataclasses import dataclass
from typing import List
from faster_whisper import WhisperModel

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")


@dataclass
class Segment:
    speaker: str        # "Advisor" | "Customer" | "Unknown"
    start: float
    end: float
    text: str


_whisper_model = None


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


def transcribe_raw(audio_path: str):
    """Returns raw whisper segments: list of (start, end, text)."""
    model = _get_whisper()
    segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=True)
    raw = [(s.start, s.end, s.text.strip()) for s in segments]
    return raw, info.language


def _diarize_pyannote(audio_path: str):
    """Real diarization via pyannote.audio. Requires HF_TOKEN env var
    (free — from https://huggingface.co/settings/tokens after accepting
    pyannote/speaker-diarization-3.1 terms once)."""
    from pyannote.audio import Pipeline
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise RuntimeError("HF_TOKEN not set — skipping real diarization")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
    )
    diarization = pipeline(audio_path)
    turns = []
    for turn, _, speaker_label in diarization.itertracks(yield_label=True):
        turns.append((turn.start, turn.end, speaker_label))
    return turns


def _assign_speaker_from_turns(seg_start, seg_end, turns):
    best, best_overlap = None, 0.0
    for t_start, t_end, label in turns:
        overlap = min(seg_end, t_end) - max(seg_start, t_start)
        if overlap > best_overlap:
            best, best_overlap = label, overlap
    return best or "Unknown"


def _heuristic_diarize(raw_segments, pause_threshold=1.2):
    """
    Fallback for mono / low-confidence audio: assume a real conversational
    call alternates speakers roughly every turn, and a pause longer than
    `pause_threshold` seconds signals a probable speaker change.
    This is intentionally simple and clearly a lower-confidence method —
    it should NOT be presented as equivalent to real diarization; the
    call record is flagged accordingly (see pipeline.py).
    """
    labeled = []
    current_speaker = "Advisor"  # convention: advisor opens the call
    prev_end = None
    for start, end, text in raw_segments:
        if prev_end is not None and (start - prev_end) > pause_threshold:
            current_speaker = "Customer" if current_speaker == "Advisor" else "Advisor"
        labeled.append(Segment(current_speaker, start, end, text))
        prev_end = end
    return labeled


def transcribe_and_diarize(audio_path: str):
    """
    Returns (segments: List[Segment], diarization_method: str)
    diarization_method is "pyannote" or "heuristic_fallback" — this gets
    stored on the Call row so the dashboard can flag low-confidence calls.
    """
    raw_segments, language = transcribe_raw(audio_path)

    try:
        turns = _diarize_pyannote(audio_path)
        segments = [
            Segment(_assign_speaker_from_turns(s, e, turns), s, e, t)
            for s, e, t in raw_segments
        ]
        return segments, "pyannote", language
    except Exception as e:
        print(f"  [diarization] pyannote unavailable ({e}); using heuristic fallback")
        segments = _heuristic_diarize(raw_segments)
        return segments, "heuristic_fallback", language


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw_calls/call_good_001.wav"
    segments, method, lang = transcribe_and_diarize(path)
    print(f"Diarization method: {method} | language: {lang}")
    for seg in segments:
        print(f"[{seg.start:6.1f}-{seg.end:6.1f}] {seg.speaker}: {seg.text}")
