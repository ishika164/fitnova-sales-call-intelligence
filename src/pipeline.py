"""
Pipeline orchestrator — runs one call through the full loop:
ingest -> transcribe+diarize -> redact PII -> analyze -> store

Idempotency: call_uid is unique in the DB. Before processing, we check if
a Call with that uid already exists and is "done" — if so, we skip it
entirely. A call is never scored twice, even if ingestion runs again on
the same folder (this answers "a call is never double-processed").

Retry: transcription and analysis calls (the two steps that hit an
external dependency — model load / API) are wrapped with a bounded retry
+ backoff. If a call exhausts retries, its status is set to "failed" and
the error is stored on the row — it does NOT crash the batch; the next
call still gets processed.
"""
import time
import traceback
from src.models import init_db, get_session, Advisor, Call, TranscriptSegment, CallScore, IssueFlag
from src.ingestion import get_adapter
from src.transcribe import transcribe_and_diarize
from src.pii_redaction import redact_segments
from src.analysis import analyze_call

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


def with_retries(fn, *args, step_name="step", **kwargs):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            print(f"    [{step_name}] attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"{step_name} failed after {MAX_RETRIES} attempts: {last_err}")


def get_or_create_advisor(session, advisor_name):
    advisor = session.query(Advisor).filter_by(name=advisor_name).first()
    if not advisor:
        # unknown advisor from source data — real system would route to a
        # review queue; here we log it clearly rather than silently guessing
        raise ValueError(
            f"Advisor '{advisor_name}' not found in org structure. "
            f"A real system would queue this for manual mapping, not silently drop the call."
        )
    return advisor


def process_call(session, record):
    existing = session.query(Call).filter_by(call_uid=record.call_uid).first()
    if existing and existing.status == "done":
        print(f"  SKIP (already processed): {record.source_ref}")
        return existing

    call = existing or Call(
        call_uid=record.call_uid,
        source=record.source,
        source_ref=record.source_ref,
        customer_ref=record.customer_ref,
        call_datetime=record.call_datetime,
    )

    try:
        advisor = get_or_create_advisor(session, record.advisor_name)
        call.advisor_id = advisor.id
        call.status = "transcribing"
        session.add(call)
        session.commit()

        segments, diar_method, language = with_retries(
            transcribe_and_diarize, record.audio_path, step_name="transcription"
        )
        call.duration_seconds = segments[-1].end if segments else 0
        call.diarization_method = diar_method

        pii_found = redact_segments(segments)
        call.pii_redacted = pii_found

        call.status = "scoring"
        session.commit()

        result = with_retries(analyze_call, segments, step_name="analysis")
        call.is_sales_call = result.is_sales_call

        # wipe old segments/scores/flags if this is a re-run
        session.query(TranscriptSegment).filter_by(call_id=call.id).delete()
        session.query(IssueFlag).filter_by(call_id=call.id).delete()
        if call.score:
            session.delete(call.score)

        for seg in segments:
            session.add(TranscriptSegment(
                call_id=call.id, speaker=seg.speaker,
                start_time=seg.start, end_time=seg.end, text=seg.text,
            ))

        if result.is_sales_call:
            session.add(CallScore(
                call_id=call.id,
                needs_discovery=result.scores.get("needs_discovery", 0),
                product_knowledge=result.scores.get("product_knowledge", 0),
                objection_handling=result.scores.get("objection_handling", 0),
                compliance=result.scores.get("compliance", 0),
                next_step_booking=result.scores.get("next_step_booking", 0),
                overall_score=result.overall_score,
                model_used="llama-3.3-70b-versatile (groq)",
            ))
            for f in result.flags:
                session.add(IssueFlag(
                    call_id=call.id, tag=f["tag"], severity=f["severity"],
                    quoted_line=f["quoted_line"], timestamp=f.get("timestamp"),
                    reason=f.get("reason"),
                ))

        call.status = "done"
        call.processing_error = None
        session.commit()
        print(f"  DONE: {record.source_ref} | sales_call={result.is_sales_call} | "
              f"overall={result.overall_score} | flags={len(result.flags)} | diarization={diar_method}")
        return call

    except Exception as e:
        call.status = "failed"
        call.processing_error = f"{e}\n{traceback.format_exc()[-1000:]}"
        session.add(call)
        session.commit()
        print(f"  FAILED: {record.source_ref} -> {e}")
        return call


def run_pipeline(source="local_folder", folder_path="data/raw_calls", db_path="data/fitnova.db"):
    init_db(db_path)
    session = get_session(db_path)
    adapter = get_adapter(source, folder_path=folder_path)
    records = adapter.list_new_calls()
    print(f"Found {len(records)} call(s) from source '{source}'")
    for record in records:
        print(f"Processing {record.source_ref} (uid={record.call_uid[:8]}...)")
        process_call(session, record)
    session.close()


if __name__ == "__main__":
    run_pipeline()
