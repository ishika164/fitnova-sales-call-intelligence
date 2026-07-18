"""
PII redaction. Runs on transcript text before it is stored or shown on any
dashboard. Regex-based on purpose: fast, deterministic, auditable — no LLM
call needed (and no risk of an LLM "helpfully" leaving PII in because it
paraphrased around it).

Scope for this prototype: phone numbers, email addresses, 12-digit-like
national ID patterns (Aadhaar-shaped), and card-number-shaped sequences.
Real deployment would extend this list; the point is the redaction step
existing in the pipeline as a hard gate, not the exhaustiveness of patterns.
"""
import re

PATTERNS = {
    "PHONE": re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"),
    "EMAIL": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "AADHAAR_LIKE": re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)"),
    "CARD_LIKE": re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
}


def redact(text: str) -> tuple[str, bool]:
    """Returns (redacted_text, was_anything_redacted)."""
    redacted_flag = False
    out = text
    for label, pattern in PATTERNS.items():
        new_out, n = pattern.subn(f"[REDACTED_{label}]", out)
        if n > 0:
            redacted_flag = True
        out = new_out
    return out, redacted_flag


def redact_segments(segments):
    """Mutates a list of transcribe.Segment in place, returns whether any
    redaction happened across the whole call (stored on Call.pii_redacted)."""
    any_redacted = False
    for seg in segments:
        seg.text, was_redacted = redact(seg.text)
        any_redacted = any_redacted or was_redacted
    return any_redacted


if __name__ == "__main__":
    samples = [
        "You can reach me at 9876543210 or priya.fitnova@gmail.com",
        "My Aadhaar is 1234 5678 9012 if you need it",
        "No PII in this line at all",
    ]
    for s in samples:
        print(redact(s))
