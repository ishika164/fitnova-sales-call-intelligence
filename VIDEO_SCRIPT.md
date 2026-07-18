# Video Walkthrough Script (~2 minutes)

Read this once, then record in your own words — don't read verbatim, the
evaluators will ask you to explain any part, so it needs to be internalized,
not memorized.

**[0:00–0:20] What it does**
"This is an end-to-end pipeline for FitNova's sales calls. A call recording
goes in, and out comes a transcript with speakers separated, a quality
score across five dimensions, and specific issue flags — each one tied to
an exact quoted line and timestamp so it's auditable, not a black box."
[Show the dashboard, Sales Director view]

**[0:20–0:50] The trade-off I'd defend hardest**
"The hardest problem wasn't scoring calls — it's stopping the model from
inventing violations that never happened. My answer: every flag has to
quote an exact line from the transcript, and after the model responds, I
check that quote actually exists in the real transcript before it's ever
stored. If it doesn't match, the flag is silently dropped. I have a test
that proves this — a deliberately fabricated flag gets dropped, real ones
survive."
[Show tests/test_pipeline_run.py output or the analysis.py grounding check]

**[0:50–1:20] What I chose not to build, and why**
"I used a free-tier hosted LLM (Groq) instead of a fully local model,
because small local models were too unreliable at structured JSON output
for something this rubric-dependent — that was worth the small dependency
given the free constraint. I also didn't build real authentication, or
push notifications on the contest workflow — those matter for production
but weren't where the 48 hours were best spent. And diarization has a
fallback heuristic for mono/low-confidence audio rather than pretending
pyannote is perfect on real call-center recordings."

**[1:20–1:50] Where it would actually fail**
"The biggest real risk is diarization quality on real, noisy call-center
audio — my synthetic test calls are cleaner than reality. I'd want to
validate against real FitNova recordings before trusting flag timestamps
at scale. Second, the rubric weights are my best guess, not calibrated
against real outcomes like churn or complaints — I'd want that feedback
loop before treating scores as ground truth."

**[1:50–2:00] Close**
"Everything from ingestion through the dashboard and the contest workflow
runs end-to-end against a real database — that's demonstrated in the repo,
not just described in the writeup."

---

## Recording tips
- Screen-record your terminal running `./run.sh` for ~10 seconds (even sped
  up) — "something real runs" is graded, showing it run is stronger than
  saying it does.
- Show the dashboard switching between the 3 role views for a few seconds
  each.
- Show one flag being contested, and the Team Leader resolving it — this is
  the feedback loop, and it's easy to forget to show.
- Keep OBS/QuickTime or your phone simple — content matters more than
  production quality here.
