# V-Vet — symptom extraction service

Turns a farmer's WhatsApp message into structured clinical findings from a fixed list of
nine signs, and decides escalation in code. One endpoint, `POST /extract`.

Built for the V-Vet coding task, 6 November 2026.

```
POST /extract   {"message": "..."}
->  {"findings": [{"sign_id": "...", "value": "yes|no|not_sure", "quote": "..."}],
     "escalate": true,
     "reason": "..."}
```

---

## Quick start

Two modes. The repo runs with **no API key and no network** — that matters for the tests and
for anyone reviewing the code before they have a provider set up.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# offline baseline, no key needed
EXTRACTOR=rule uvicorn app.main:app --reload --port 8000

# with a model
cp .env.example .env          # then put your key in LLM_API_KEY
uvicorn app.main:app --reload --env-file .env --port 8000
```

```bash
curl -s localhost:8000/extract -H 'Content-Type: application/json' \
  -d '{"message": "There is foam coming from her nose and she cannot get up."}'
```

```json
{
  "findings": [
    {"sign_id": "froth_nose_mouth", "value": "yes", "quote": "foam coming from her nose"},
    {"sign_id": "unable_to_stand", "value": "yes", "quote": "she cannot get up"}
  ],
  "escalate": true,
  "reason": "Escalate: critical sign reported (froth_nose_mouth=yes, unable_to_stand=yes)."
}
```

That is a **real model answer**, captured on 2026-11-10 through `POST /extract` with `EXTRACTOR=llm`
against `deepseek-chat` — not a mock. `GET /health` reports `"extractor": "llm"` when it is the model
answering, so you never have to guess which path produced a response.

Tests and the offline evaluation:

```bash
pytest                                    # 52 tests, no network, no key
python scripts/evaluate.py --extractor rule --show-errors
```

Any provider with an OpenAI-compatible `/chat/completions` endpoint works — DeepSeek (default),
Groq, OpenRouter, Together, Ollama. It is configuration, not architecture: see `.env.example`.

| Variable | Default | Notes |
|---|---|---|
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | any OpenAI-compatible base URL |
| `LLM_MODEL` | `deepseek-chat` | |
| `LLM_API_KEY` | empty | never committed; `.env` is gitignored |
| `EXTRACTOR` | `auto` | `llm`, `rule`, or `auto` = llm when a key is set |

`GET /health` reports which extractor is live, so a reviewer can always tell whether an answer
came from a model or from the baseline.

---

## How it works

```
message
  |
  |-- LLMExtractor ------------------------------------------------+
  |     prompt (nine signs, verbatim-quote rule, Shona note)       |
  |     -> model -> raw text                                        |
  |     -> parse JSON (tolerates fences and prose)                  |
  |     -> clean_findings: shape, grounding, repair, dedupe         |
  |                                                                 |
  |-- RuleExtractor (offline baseline) -----------------------------+
  |     regex per sign + sentence window + hedge/negation cues      |
  |
  +-> enforce_contract   (same clean_findings, once more, at the boundary)
        |
        +-> decide_escalation   (pure function, no model involved)
              |
              +-> response
```

| File | Responsibility |
|---|---|
| `app/signs.py` | the nine signs, their meanings, which three are critical — **one source of truth** |
| `app/prompt.py` | the extraction prompt, generated from `signs.py` |
| `app/llm.py` | provider-agnostic chat client, one function |
| `app/extract.py` | the two extractors, plus the boundary check |
| `app/validate.py` | parse, ground, repair, dedupe |
| `app/escalate.py` | the escalation rule |
| `app/main.py` | two routes: `/extract` and `/health` |
| `data/eval_cases.jsonl` | 18 labelled cases, including the five samples and Shona |
| `scripts/evaluate.py` | per-sign precision/recall, escalation matrix, grounding rate |

---

## Decisions

These are the calls I made where the task left room, and why.

**1. The model never decides escalation.** It reports findings; `decide_escalation` is a pure
function with one rule. A rule you can read is a rule you can argue with, test, and change
without re-prompting anything.

**2. `not_sure` escalates.** This is the most important decision in the service. A farmer who is
unsure about froth, a cloudy eye, or an animal that cannot stand is still describing an
emergency. The two mistakes do not cost the same: a needless call costs a phone call, a missed
emergency can cost the animal. So every ambiguity resolves toward the alarm, never away from it.

**3. The quote is the evidence, so it must be grounded.** Every returned quote is checked against
the message. If the model paraphrases or translates, the finding is not trusted as written. This
is the cheapest anti-hallucination check available and it catches the failure that matters —
a confident, well-formed, invented finding.

**4. But an ungrounded *critical* finding is downgraded, not deleted.** Here the safe direction
inverts. Deleting it would be silent, and silence on froth or a downed animal is the expensive
failure. So it survives as `not_sure` and the caller is told why in `reason`. A model that
paraphrases a real emergency cannot switch the alarm off; the cost is a false alarm when it
invents one outright, and I would rather pay that. `tests/test_samples.py` pins this behaviour
down, including a model that hallucinates foam.

The same rule has a cost, and it is worth naming: a model that reports `no` for a critical sign
with a quote that is not in the message gets repaired to `not_sure`, so a healthy animal can raise
an alarm. I would rather explain a false alarm to a vet than explain a missed downed animal.

**5. A hedged `yes` becomes `not_sure`.** If the quote contains "I think", "maybe", "not sure",
"ndinofunga", "pamwe", the value is downgraded. Deterministic safety net under the model's
judgement; again, it can only move toward caution.

**6. Duplicates collapse to the strongest claim** (`yes` > `not_sure` > `no`). If the model
reports the same sign twice with different certainty, the stronger one wins for triage purposes.

**7. `no` means the message explicitly negates the sign.** "No foam", "no ticks". A sign nobody
mentions is simply absent from `findings`. "The calf is fine" is not evidence of eight negative
findings — inferring those would put words in the farmer's mouth, and the task says to report
only what is mentioned.

One asymmetry, stated because it is a real collision between this decision and Decision 2: the
**rule baseline** never reports `no` on a critical sign — it reports `not_sure`. A keyword regex
cannot tell "no foam" (reassuring) from a clause it has mis-parsed, so on the three signs where
being wrong is expensive, the alarm wins. The **model path** still returns `no` when the quote is
grounded. But `EXTRACTOR=rule` is precisely what a reviewer runs without a key, so the honest
summary is: on the baseline, a message that denies all three critical signs raises an alarm; on the
model, it does not.

**8. Validation runs at the boundary, not only inside the extractor.** `enforce_contract` re-runs
the same checks on whatever an extractor produced. Belt and braces, and it means the contract
holds for a future extractor nobody has written yet, not just the two here.

**9. The response has exactly the three keys the task specified.** No `model`, no `confidence`,
no `mode`. Adding fields to someone else's contract is a change to their system, not a feature
of mine. Extractor mode is on `/health` instead.

**10. A model outage is a 502, not a 500.** "The provider timed out" and "your JSON was wrong"
are different problems and the caller should be able to tell them apart.

**11. A rule-based baseline ships alongside the model.** It exists so the repo runs offline, and
because a baseline is how you find out whether the model earns its cost. Its number is not
flattering and its known misses are left visible rather than tuned away — see Measurement.

**12. `response_format` is deliberately not sent.** Some OpenAI-compatible providers accept it
and ignore it, others reject it. The prompt asks for JSON and the parser is built to survive a
model that wraps its answer in prose or a code fence. Fewer provider-specific surprises.
---

## How I would measure whether the extraction is accurate

`scripts/evaluate.py` scores an extractor against `data/eval_cases.jsonl`: per-sign
precision/recall/F1, an escalation confusion matrix, and the share of returned quotes that
actually appear in the message.

The offline baseline, today:

```
extractor: rule   cases: 18

sign                     P     R     F1   support
reduced_appetite      1.00  1.00   1.00   4
weakness              1.00  0.67   0.80   3
swelling              1.00  1.00   1.00   2
rapid_breathing       1.00  1.00   1.00   2
cloudy_eye            1.00  0.75   0.86   4
froth_nose_mouth      1.00  1.00   1.00   5
red_urine             1.00  1.00   1.00   2
unable_to_stand       1.00  0.80   0.89   5
ticks                 1.00  1.00   1.00   4

escalation
  caught (escalate, was an emergency) : 7
  missed (no escalation, was one)     : 0   <- the dangerous cell
  false alarm                         : 0
  correctly quiet                     : 11

quote grounding: 28/28 (100%) of returned quotes appear in the source message
```

**Read that table with suspicion, because I do.** Three reasons it is optimistic:

1. **18 cases, and five of them are the task's own samples.** I had read those before writing a
   line of the baseline.
2. **The baseline was written by the same person who wrote the labels.** Precision of 1.00 is
   cheap when your patterns and your label set come from the same imagination.
3. **Three misses are left visible on purpose** (`--show-errors` prints them): "she can stand",
   "ari kuneta" (tired), "eyes are white". I could add three regexes and turn them green. That
   would measure my ability to fit 18 examples, not the extraction.

What the table *is* good for: it proves the pipeline works end to end, that escalation catches
every emergency in the set, and that it never invents a quote. The dangerous cell is the one to
watch, and it is zero.

### The model, on the same cases

Captured **2026-11-10** against `deepseek-chat`, same 18 cases, real API calls — not a scripted mock:

```
extractor: llm   cases: 18

sign                     P     R     F1   support
----------------------------------------------
reduced_appetite      1.00  1.00   1.00   4
weakness              1.00  1.00   1.00   3
swelling              1.00  1.00   1.00   2
rapid_breathing       1.00  1.00   1.00   2
cloudy_eye            1.00  1.00   1.00   4
froth_nose_mouth      1.00  1.00   1.00   5
red_urine             1.00  1.00   1.00   2
unable_to_stand       1.00  1.00   1.00   5
ticks                 1.00  1.00   1.00   4

escalation
  caught (escalate, was an emergency) : 7
  missed (no escalation, was one)     : 0   <- the dangerous cell
  false alarm                         : 0
  correctly quiet                     : 11

quote grounding: 31/31 (100%) of returned quotes appear in the source message
```

The model is cleaner than the baseline on every sign, and the gap is the interesting part: the
baseline's misses are **vocabulary**, not reasoning — `"she can stand"`, `"ari kuneta"` (tired),
`"eyes are white"` are phrasings no regex I wrote anticipated. The model handled all three without
being told.

**Every caveat above applies twice as hard here.** A perfect score on 18 cases I also wrote is
evidence that the pipeline works end to end — validation, grounding, escalation, serialisation —
not evidence that the model generalises. The measurement section below is what would actually
change my mind.

**The measurement I would actually trust, in order of how much it would change my mind:**

1. **A real sample.** 200–300 actual WhatsApp messages, stratified by language (English / Shona /
   mixed), by sign rarity, and by case outcome. Everything above is a smoke test until this exists.
2. **Two annotators, then adjudication.** An animal-health worker and I label independently,
   resolve disagreements, and report **inter-annotator agreement first** (Cohen's kappa). That
   number is the ceiling: if two humans agree 85% of the time, a model scoring 92% on the same
   data is measuring noise, not quality.
3. **The headline metric is not accuracy — it is the critical-miss rate.** How many messages that
   should have escalated did not. I would ship nothing that misses a critical sign, and I would
   accept a fair number of false alarms to get there. Accuracy hides that trade-off; this metric
   is the trade-off.
4. **Stratify every number by language.** A model that is strong in English and blind in Shona is
   worse than useless for these users, because most of them write Shona first.
5. **Watch grounding in production.** If the rate of quotes that are not verbatim drops, the model
   has started paraphrasing and the quotes stop being evidence.
6. **LLM-as-judge only for the "did we miss a mention?" question**, spot-checked by a human, never
   as the final authority on escalation.
7. **Log everything**, then mine the near misses — repaired and dropped findings are the cheapest
   source of new labelled cases.

---

## Known gaps I chose not to hide

- **Zero findings is not escalated.** The task defines escalation over three signs, and I followed
  it exactly. But a long, detailed message that yields no findings is either genuinely healthy or
  a total miss, and today those two look identical. That is the first thing I would fix (see below).
- **The baseline is coarse.** It quotes the whole sentence rather than the phrase, and it misses
  Shona vocabulary outside the list I wrote. The model path produces tighter quotes.
- **The baseline's regexes over-trigger.** `ziso` (Shona for "eye") fires `cloudy_eye` on any eye
  mention, `saliva` and `spit` fire `froth_nose_mouth`, and `ticks?` has no word boundary so
  "sticks" matches. Every one of those escalates rather than misses, so the direction is right —
  but they are false alarms, and they are listed here rather than tuned away.
- **Explicit negations of critical signs escalate on the baseline.** "No foam, no cloudy eyes,
  she is just off her food" raises an alarm under `EXTRACTOR=rule`, because the rule path reports
  `not_sure` on the three critical signs rather than `no` (see Decision 7). The model path does
  not. This is the cost of the second safety layer, and it is exactly the kind of thing a clinic
  would tune against real message volume.
- **A paraphrased `no` on a critical sign escalates.** If the model reports `unable_to_stand = no`
  with a quote that is not in the message ("she is standing" when the message says "the cow is up
  and walking fine"), grounding fails and the finding is repaired to `not_sure`. That is the trade
  in Decision 4, stated plainly: a false alarm on a healthy animal is the price of never silencing
  a real one.
- **No retry on malformed model output.** One bad JSON answer is a 502. A single retry that feeds
  the parser error back would recover most of these.
- **Shona coverage is thin.** `haisi kudya`, `mbandabvu`, `haagone kumira`, `yakasviba`, `kuneta`
  are handled. The full vocabulary of cattle disease description is not, and it is not something I
  can invent from here.
- **No auth, no rate limiting, no retention policy.** Fine for a task, not for production.

---

## What I would do with more time

1. **Guard the empty-findings case.** Route "long message, zero findings" to a human queue instead
   of trusting the absence. It is the one failure mode where the system is confidently wrong.
2. **Retry once on unparseable output**, feeding the parser error back, then fall back to the
   baseline rather than returning 502.
3. **Schema-constrained decoding** where the provider supports it, keeping the validator as the
   backstop instead of the only defence.
4. **Prompt versioning with the eval in CI.** Every prompt change becomes a measured change, not a
   vibe, and the 18 cases grow into the 300 from real traffic.
5. **Latency and cost budgets.** p50/p95 per message, tokens per request, and an alert when either
   doubles. A triage call that takes six seconds is a triage call the farmer abandons.
6. **A review queue for repaired and dropped findings.** Those are the model's near misses and the
   best labelled data in the system.
7. **Cache by message hash.** WhatsApp delivers duplicates and retries; paying twice for the same
   message is free money for the provider.
8. **Auth, rate limits, and a retention story.** These are messages from named farms about their
   animals. Who can read them, and for how long, is a product decision, not a detail.

---

## How I used AI tools

I built this with an AI coding assistant (Claude Code) as the authoring loop: it wrote the first
draft of each module from my direction, and I read, tested, and changed what came back. That is
how I work on everything else, and it is worth being precise about what it does and does not mean.

What the tools did: scaffolding, the prompt draft, the first version of the regex patterns, and
most of the typing.

What decided the shape of the service, and what I will defend in the interview: validating at the
boundary as well as inside the extractor; grounding quotes against the message; keeping an
ungrounded *critical* finding as `not_sure` instead of deleting it; downgrading a hedged `yes`;
deciding escalation in a pure function; and shipping the baseline so the model has something to be
measured against.

Three bugs the tests caught, all worth knowing about because they are the kind that survive review:

- `model_dump()` on a `str`-Enum returns `SignID.ticks`, not `ticks`, so validation silently
  rejected every finding and the API returned an empty list with a 200. `mode="json"` fixed it.
- The negation rule read text before the match, which meant "not eating" — the *positive* form of
  reduced_appetite — would have marked itself absent. Looking only backwards from the match kept it
  positive, and that is why the rule now has a comment saying so.
- A 30-character lookback is a *window*, not a clause. "No foam from the nose but she cannot
  stand." read the "No" across the "but" and returned `unable_to_stand = no`, so a downed animal
  did not escalate — the one cell the table calls dangerous. Negation is now bounded by the nearest
  clause boundary (`but`, `however`, `though`, `although`, `;`, `,`), and the rule extractor can no
  longer emit `no` on a critical sign at all: it falls back to `not_sure`. Two mechanisms, one
  direction — toward the alarm. `tests/test_rule_negation.py` pins the exact sentence.

You can run `pytest` and `python scripts/evaluate.py` and see all of this for yourself in about
thirty seconds. I would rather be quizzed on the decisions than on the prose.
