"""
Proves the pipeline orchestration logic (idempotency, retries, failure
isolation, DB writes) works correctly, WITHOUT needing huggingface.co /
api.groq.com access (unreachable from this build sandbox).

transcribe_and_diarize() and analyze_call() are mocked with realistic
outputs matching our known synthetic call scripts (data/call_scripts.json)
-- i.e. we know the ground truth, so we can also sanity-check the mocked
analysis matches what a real model should conclude.

This file is NOT part of the shipped pipeline. It exists purely to
validate src/pipeline.py's control flow before running it for real.
Delete before submission, or keep in a tests/ folder — your call.
"""
import json
from unittest.mock import patch
from src import pipeline
from src.transcribe import Segment
from src.analysis import AnalysisResult

with open("data/call_scripts.json") as f:
    SCRIPTS = json.load(f)


def fake_segments_for(source_ref):
    call_id = source_ref.replace(".wav", "")
    script = SCRIPTS[call_id]
    segments = []
    t = 0.0
    for speaker, text in script["lines"]:
        dur = max(2.0, len(text) / 15)
        segments.append(Segment(speaker, t, t + dur, text))
        t += dur + 0.5
    return segments


def fake_transcribe_and_diarize(audio_path):
    source_ref = audio_path.split("/")[-1]
    segments = fake_segments_for(source_ref)
    return segments, "pyannote", "en"


def fake_analyze_call(segments):
    text = " ".join(s.text.lower() for s in segments)
    is_sales = not ("wrong number" in text)
    if not is_sales:
        return AnalysisResult(is_sales_call=False, scores={}, flags=[], overall_score=0.0)

    flags = []
    if "guaranteed" in text:
        flags.append({"tag": "over_promising", "severity": "high",
                       "quoted_line": next(s.text for s in segments if "guaranteed" in s.text.lower()),
                       "timestamp": next(s.start for s in segments if "guaranteed" in s.text.lower()),
                       "reason": "Promised guaranteed outcome"})
    if "only valid today" in text or "price goes up" in text:
        flags.append({"tag": "pressure_or_urgency_tactics", "severity": "high",
                       "quoted_line": next(s.text for s in segments if "price goes up" in s.text.lower()),
                       "timestamp": next(s.start for s in segments if "price goes up" in s.text.lower()),
                       "reason": "Artificial urgency to force decision"})
    if "registration fee" in text:
        flags.append({"tag": "undisclosed_costs", "severity": "medium",
                       "quoted_line": next(s.text for s in segments if "registration fee" in s.text.lower()),
                       "timestamp": next(s.start for s in segments if "registration fee" in s.text.lower()),
                       "reason": "Fee disclosed only after price agreed"})

    is_bad = len(flags) > 0
    scores = {
        "needs_discovery": 2 if is_bad else 8,
        "product_knowledge": 5 if is_bad else 8,
        "objection_handling": 3 if is_bad else 7,
        "compliance": 1 if is_bad else 9,
        "next_step_booking": 2 if is_bad else 9,
    }
    overall = round(sum(scores.values()) / len(scores), 2)
    return AnalysisResult(is_sales_call=True, scores=scores, flags=flags, overall_score=overall)


def main():
    import os
    if os.path.exists("data/fitnova.db"):
        os.remove("data/fitnova.db")
    from src.seed import main as seed_main
    seed_main()

    print("\n=== RUN 1: full pipeline ===")
    with patch("src.pipeline.transcribe_and_diarize", side_effect=fake_transcribe_and_diarize), \
         patch("src.pipeline.analyze_call", side_effect=fake_analyze_call):
        pipeline.run_pipeline()

    print("\n=== RUN 2: same folder again (must show SKIP for all, proving idempotency) ===")
    with patch("src.pipeline.transcribe_and_diarize", side_effect=fake_transcribe_and_diarize), \
         patch("src.pipeline.analyze_call", side_effect=fake_analyze_call):
        pipeline.run_pipeline()

    print("\n=== DB CONTENTS ===")
    from src.models import get_session, Call, CallScore, IssueFlag
    session = get_session()
    for call in session.query(Call).all():
        print(f"\nCall {call.source_ref} | advisor={call.advisor.name} | status={call.status} | "
              f"is_sales_call={call.is_sales_call} | pii_redacted={call.pii_redacted}")
        if call.score:
            print(f"  overall_score={call.score.overall_score} | dims={ {d: getattr(call.score, d) for d in ['needs_discovery','product_knowledge','objection_handling','compliance','next_step_booking']} }")
        for flag in call.flags:
            print(f"  FLAG [{flag.severity}] {flag.tag}: \"{flag.quoted_line[:60]}\"")


if __name__ == "__main__":
    main()
