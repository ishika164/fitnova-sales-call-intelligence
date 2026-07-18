"""
Analysis engine — scores call quality and tags issues.

Reliability strategy (the actual answer to "how you stop the model
inventing flags"):
  1. Force JSON-only output via the API's json_object response mode —
     removes prose-wrapping and markdown-fence failures.
  2. Every flag MUST include a quoted_line copied from the transcript.
  3. GROUNDING CHECK (the real anti-hallucination gate): after the model
     responds, every quoted_line is checked against the actual transcript
     text. If it's not a genuine substring match (fuzzy-tolerant for minor
     whitespace/punctuation), the flag is DROPPED before it ever reaches
     the database. A flag that can't be traced to a real line in the call
     never becomes an issue the advisor has to contest.
  4. Closed tag vocabulary — the model is given the exact list of allowed
     tags and told to use ONLY those. Any tag outside the list is dropped.

Uses Groq's free-tier API (Llama 3.3 70B) — no cost, but does require
internet access to api.groq.com (not reachable from the build sandbox,
same constraint as transcription — see README).
"""
import os
import json
import re
import difflib
from dataclasses import dataclass, field
from typing import List

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

RUBRIC_DIMENSIONS = [
    "needs_discovery",
    "product_knowledge",
    "objection_handling",
    "compliance",
    "next_step_booking",
]

ALLOWED_TAGS = {
    "no_needs_discovery": "Advisor pitched without understanding the customer's goals, budget, or constraints",
    "over_promising": "Advisor guaranteed specific results or outcomes that cannot be guaranteed",
    "pressure_or_urgency_tactics": "Advisor used artificial urgency or high pressure to force an immediate decision",
    "price_before_value": "Advisor led with price before explaining what the customer is getting",
    "undisclosed_costs": "Advisor revealed additional costs/fees only after initial price was already agreed to",
    "weak_or_missing_trial_booking": "Call ended without a clear, confirmed next step or trial booking",
    "talking_over_customer": "Advisor interrupted or spoke over the customer, based on transcript cues",
}

SYSTEM_PROMPT = f"""You are a strict sales-call quality auditor for FitNova, a fitness coaching company.
You will be given a diarized call transcript between an Advisor and a Customer.

Score the call on these 5 dimensions, each 0-10 (10 = excellent):
{json.dumps(RUBRIC_DIMENSIONS)}

Then identify issues using ONLY these exact tag names — do not invent new tags:
{json.dumps(ALLOWED_TAGS, indent=2)}

Rules:
- Only flag an issue if you can quote the EXACT line from the transcript that shows it.
- The quoted_line must be copied verbatim from the transcript, not paraphrased.
- severity must be one of: "low", "medium", "high"
- If the call is not a real sales conversation (wrong number, internal call, silence), set is_sales_call to false and return empty scores/flags.
- Respond with JSON ONLY, no markdown fences, no commentary. Exact schema:

{{
  "is_sales_call": true,
  "scores": {{"needs_discovery": 0, "product_knowledge": 0, "objection_handling": 0, "compliance": 0, "next_step_booking": 0}},
  "flags": [
    {{"tag": "over_promising", "severity": "high", "quoted_line": "exact text from transcript", "timestamp": 12.5, "reason": "one sentence why this is a problem"}}
  ]
}}
"""


@dataclass
class AnalysisResult:
    is_sales_call: bool
    scores: dict
    flags: List[dict] = field(default_factory=list)
    overall_score: float = 0.0
    raw_model_output: str = ""
    dropped_flags: List[dict] = field(default_factory=list)  # for transparency/debugging


def _build_transcript_text(segments):
    lines = []
    for seg in segments:
        lines.append(f"[{seg.start:.1f}] {seg.speaker}: {seg.text}")
    return "\n".join(lines)


def _call_groq(transcript_text: str) -> str:
    import requests
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not set. Get a free key at https://console.groq.com/keys "
            "and export GROQ_API_KEY=... before running."
        )
    resp = requests.post(
        GROQ_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": GROQ_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"TRANSCRIPT:\n{transcript_text}"},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _is_grounded(quoted_line: str, transcript_text: str, threshold=0.85) -> bool:
    """The anti-hallucination check. Exact substring match first (fast path),
    then fuzzy match against transcript lines to tolerate minor whitespace/
    punctuation differences the model might introduce."""
    norm_quote = _normalize(quoted_line)
    norm_transcript = _normalize(transcript_text)
    if norm_quote and norm_quote in norm_transcript:
        return True
    # fuzzy fallback: compare against each transcript line
    for line in transcript_text.split("\n"):
        ratio = difflib.SequenceMatcher(None, norm_quote, _normalize(line)).ratio()
        if ratio >= threshold:
            return True
    return False


def analyze_call(segments) -> AnalysisResult:
    transcript_text = _build_transcript_text(segments)
    raw_output = _call_groq(transcript_text)

    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        # one repair attempt: strip accidental markdown fences
        cleaned = re.sub(r"^```json|```$", "", raw_output.strip())
        parsed = json.loads(cleaned)

    is_sales_call = parsed.get("is_sales_call", True)
    scores = parsed.get("scores", {}) or {}
    raw_flags = parsed.get("flags", []) or []

    accepted_flags, dropped_flags = [], []
    for flag in raw_flags:
        tag = flag.get("tag")
        quoted = flag.get("quoted_line", "")
        severity = flag.get("severity", "low")

        if tag not in ALLOWED_TAGS:
            dropped_flags.append({**flag, "drop_reason": "tag not in allowed vocabulary"})
            continue
        if severity not in ("low", "medium", "high"):
            flag["severity"] = "low"
        if not _is_grounded(quoted, transcript_text):
            dropped_flags.append({**flag, "drop_reason": "quoted_line not found in transcript (likely hallucinated)"})
            continue
        accepted_flags.append(flag)

    valid_scores = [scores.get(d, 0) for d in RUBRIC_DIMENSIONS if isinstance(scores.get(d), (int, float))]
    overall = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else 0.0

    return AnalysisResult(
        is_sales_call=is_sales_call,
        scores=scores,
        flags=accepted_flags,
        overall_score=overall,
        raw_model_output=raw_output,
        dropped_flags=dropped_flags,
    )


if __name__ == "__main__":
    from src.transcribe import transcribe_and_diarize
    segments, method, lang = transcribe_and_diarize("data/raw_calls/call_bad_001.wav")
    result = analyze_call(segments)
    print("is_sales_call:", result.is_sales_call)
    print("scores:", result.scores, "overall:", result.overall_score)
    print(f"accepted flags: {len(result.flags)}, dropped (hallucinated/invalid): {len(result.dropped_flags)}")
    for f in result.flags:
        print(" -", f)
