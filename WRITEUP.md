# FitNova Call Intelligence — Design Writeup

## A. System Design

**Pipeline:** Ingestion → Transcription/Diarization → PII Redaction → Analysis
→ Storage → Surfacing → Feedback. See `system_design.md` for the diagram.

**Ingestion is source-agnostic by construction, not by intent.** Every source
implements one `SourceAdapter` interface and returns a common
`RawCallRecord` shape (`src/ingestion.py`). The rest of the pipeline never
imports a vendor-specific type. Swapping or adding a telephony/CRM vendor
means writing one new adapter class and registering it — zero changes
anywhere downstream. I built `LocalFolderAdapter` for this prototype
(clearly labeled as the mocked source in the README), but the interface it
implements is the real deliverable.

**Where automation adds the most value, in priority order:**

1. **Analysis (scoring + tagging)** — this is the entire point of the
   system. Manual review only covers a handful of calls per advisor per
   week; automated analysis covers 100%. This is the highest-leverage stage
   and where I spent the most engineering effort (the grounding/anti-
   hallucination check specifically).
2. **Transcription + diarization** — a hard prerequisite for #1, but not
   where the differentiated value is; I used an off-the-shelf model
   (Whisper) rather than building anything custom here.
3. **Surfacing / dashboards** — turns scores into something a Team Leader
   actually acts on. Without role-specific views, a pile of scores in a
   database helps no one.
4. **Feedback loop** — lower priority than the above three for a first
   version, but necessary for trust: an automated system that flags people
   with no appeal path will be resisted or ignored by advisors. I built a
   minimal version (contest + resolve) rather than a fuller workflow
   (notifications, escalation, SLA tracking) — see trade-offs below.

Ingestion itself is comparatively low-effort to automate well (it's mostly
plumbing), which is why I invested less design time there relative to
analysis, even though it's listed first in the pipeline.

## B. Analysis Engine

**Rubric (5 dimensions, 0–10 each, averaged into `overall_score`):**
`needs_discovery`, `product_knowledge`, `objection_handling`, `compliance`,
`next_step_booking`. These roll up per-call, then average per advisor, per
team, and per org — same aggregation logic at every level, no special-casing
(see `dashboard/app.py`).

I chose a simple mean over a weighted score because weights would need real
calibration data (e.g. "does compliance matter 2x more than product
knowledge?") that doesn't exist yet. A flat average is honest about that —
it's a defensible v1, not a claim of a validated model.

**Issue-tag taxonomy** (`src/analysis.py`, `ALLOWED_TAGS`): `no_needs_discovery`,
`over_promising`, `pressure_or_urgency_tactics`, `price_before_value`,
`undisclosed_costs`, `weak_or_missing_trial_booking`, `talking_over_customer`
— each carries a severity (`low`/`medium`/`high`), a verbatim quoted line, a
timestamp, and a one-line reason. This is a **closed vocabulary**: the model
is instructed to use only these tags, and any tag outside the list is
programmatically dropped regardless of what the model outputs.

**Reliable tagging — this is the part I'd defend hardest:**
1. JSON-object response mode removes markdown-fence and prose-wrapping
   failures.
2. Every flag must carry a `quoted_line` copied verbatim from the transcript.
3. **Grounding check**: after the model responds, every `quoted_line` is
   checked against the actual transcript — exact substring match first,
   fuzzy match (difflib, 0.85 threshold) as a tolerance for minor
   whitespace/punctuation differences. If a quote can't be found in the real
   transcript, the flag is dropped *before it reaches the database* — an
   advisor never has to contest a flag that was invented.
4. Closed tag vocabulary (above) — an unrecognized tag is dropped the same
   way.

This isn't theoretical — `tests/test_pipeline_run.py` and the inline test in
`src/analysis.py` run this against a transcript with one deliberately
fabricated quote and one deliberately invalid tag; both are dropped, the two
genuine flags survive. That's the actual behavior, not a description of
intended behavior.

**Edge cases and how each is actually handled (not just described):**

| Edge case | Handling |
|---|---|
| Mono / poor diarization | Primary: pyannote.audio. Fallback: pause-based heuristic speaker alternation, explicitly lower-confidence, logged as such (`diarization_method` on the call). **Confirmed in practice, not just designed for**: during actual testing, pyannote failed with a real `torchaudio` version-compatibility error, and the fallback caught it and ran automatically — observed live, not simulated. Not presented as equivalent to real diarization. |
| Hindi-English code-switching | Whisper handles code-switched speech natively reasonably well; not separately engineered for in this prototype. Documented as a known gap — I'd validate against real code-switched calls before trusting scores on them, and would consider a language-ID pass per segment if quality was poor. |
| Non-sales calls (wrong number, internal) | Model sets `is_sales_call: false`; the call is stored (for audit) but excluded from all scoring/aggregation. Tested with a synthetic wrong-number call. |
| PII that must be redacted | Regex-based redaction (`src/pii_redaction.py`) runs before storage — phone numbers, emails, Aadhaar-shaped and card-shaped number sequences. Deterministic on purpose: no risk of an LLM "helpfully" leaving PII in a paraphrase. |
| Hallucinated / false-positive tags | The grounding check above — the real answer to this, not a caveat. |
| Vendor API failures, retries, idempotency | Bounded retry + backoff around transcription and analysis calls (`src/pipeline.py: with_retries`). A call's `call_uid` is deterministic from its source identity; a `Call` with status `done` and matching `call_uid` is skipped on re-ingestion — proven by running the pipeline twice against the same folder (second run: all `SKIP`). Failures are isolated per-call (`status="failed"`, error logged) and don't crash the batch. |

## C. Data & Storage

`Org → Team → Advisor → Call → {TranscriptSegment, CallScore, IssueFlag}`,
with `IssueFlag → FlagContest`. Full schema in `src/models.py`.

Org structure is **data, not config** — adding a team or advisor is an
`INSERT` (`src/seed.py`), never a schema or code change. This is what "grows
without manual reconfiguration" means concretely.

`IssueFlag` is a separate table from `CallScore` rather than a JSON blob on
the call, because flags are individually addressable, contestable, and
auditable — the contest/resolution workflow needs a row per flag with its
own status, not a shared blob that has to be parsed and rewritten on every
contest.

`TranscriptSegment` stores per-speaker-turn rows with timestamps rather than
one text blob per call, because every flag needs to point at an exact,
navigable moment in the call — the brief requires this explicitly, and a
single text blob can't support it.

SQLite for this prototype — real deployment at "hundreds of advisors" scale
would move to Postgres, but the schema doesn't need to change to do that.

## Trade-offs, what I chose not to build, and where this fails

**Deliberately out of scope for this prototype:**
- Real authentication/login — the dashboard uses a role-switcher and a
  name-based selector as a stand-in. A real system needs SSO tied to the
  `Advisor`/`Team` tables.
- Notification/escalation on the feedback loop (e.g. notify a Team Leader
  when a flag is contested) — the resolution workflow exists but is pull-based
  (a Team Leader has to open the dashboard), not push-based.
- Weighted or calibrated scoring — see rubric note above.
- Code-switching-specific handling — flagged as a known gap, not solved.
- Full observability/monitoring on the pipeline (I have per-call error
  logging, not aggregate pipeline health metrics).

**Where this would break in production, honestly:**
- **Diarization quality on real call-center audio** is the single biggest
  risk. Real recordings are noisier and more overlapping than our synthetic
  test calls; the heuristic fallback is a reasonable stopgap, not a
  production-grade answer. I'd want to validate pyannote's accuracy against
  a sample of real FitNova calls before trusting flag timestamps at scale.
- **The rubric and tag taxonomy are my best guess, not calibrated against
  real outcomes** (e.g. which flags actually correlate with churn or
  complaints). I'd want a feedback loop from real customer outcomes, not
  just advisor contests, before treating scores as ground truth.
- **Groq's free tier has rate limits** that would need addressing (queuing,
  backoff tuning, or a paid tier) at "hundreds of advisors" call volume —
  fine for this prototype, not fine at scale.
- **The grounding check catches fabricated quotes, not subtler failures**
  like a real quote used to support the wrong tag, or a technically-accurate
  flag applied with unfair severity. That needs human review sampling, which
  the contest feature partially provides but doesn't fully solve.
