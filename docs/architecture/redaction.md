# Redaction

How a transcript loses its personal data before it is written, which instrument does it, and
what each way of running it catches and costs.

## What runs

The service redacts every run it records when `REDACTION=presidio` is set. It uses Presidio's
analyzer, from the `redaction` extra, and replaces each finding with its entity type:
`Forward it to <PERSON>`. A writer that redacted its own transcript says so in `redaction`, and
the service leaves that record alone. The library half has the same function, `redact_run`, for
a consumer that wants to redact before the transcript leaves its machine.

Every record then says what happened. `redaction` names the instrument, its mode, the model and
its revision, and the entity types it looked for. `extra.redaction` holds how many strings were
examined and how many findings of each type there were, so a run with nothing found reads as
examined and clean, not as never examined.

## What is looked for

People, places, email addresses, phone numbers, IBANs, card numbers, IP addresses and the Dutch
citizen service number, which is recognised with the eleven test because Presidio ships no Dutch
recognizer.

Left out by default, each for a measured reason: Presidio's US and UK identifiers fire on job ids
and token counts; dates fire on "Friday" and "7200 seconds"; organisations fire on the name of
the cluster. None of those is personal data in an agent transcript and redacting them makes the
record useless for what it is kept for. The cost is that a date of birth is not caught unless a
deployment adds `DATE_TIME` to `REDACTION_ENTITIES`.

## The three modes, measured

`scripts/measure_redaction.py` runs each mode over twelve hand-written sentences in English and
Dutch, with synthetic names and two sentences that contain nothing personal. That is a smoke test
of the choice, not a benchmark. Measured on 2026-09-13, CPU only:

| mode | caught of 21 | words wrongly removed | per sentence |
|---|---|---|---|
| patterns only | 6 | 0 | about 5 ms |
| spaCy, English and Dutch large models, with allow-list | 21 | 6 | about 20 ms |
| GLiNER multilingual PII, with allow-list | 21 | 4 | about 200 ms |

**Patterns only** is what runs when no model is configured. It found every email, phone number,
IBAN and citizen service number, and none of the ten names or four places. The instrument string
says `patterns only, no names or places` so no reader takes it for more.

**spaCy** needs one model per language, and each model tags ordinary words of the other language
as names: the English model took "Stuur het rapport naar" into a person, the Dutch model took
"Snellius". Running both merges both sets of errors.

**GLiNER** is one multilingual model. Its errors on the sample were titles and neighbouring
words, "Mevrouw" and "Bel", swallowed into the name after them. Revision
`1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d` of `urchade/gliner_multi_pii-v1`, Apache-2.0.

Both models tag a site's own vocabulary, cluster and partition names, as places. The allow-list
fixes that, and it is deployment configuration: `REDACTION_ALLOW_LIST` in the overlay.

## What it costs on a long transcript

One message of about 1,500 words, CPU only: spaCy took 0.6 seconds, about 2,350 words a second;
GLiNER took 6 seconds, about 250 words a second. An agent transcript of 50,000 words is therefore
about 20 seconds with spaCy and over three minutes with GLiNER, on the request that writes it.

So: GLiNER where the pod has a GPU, spaCy where it does not and the transcripts are mostly one
language, and redaction in the consumer before the post where a long transcript must not hold a
request open. Moving redaction off the request path, recording first and redacting after, is not
built; it would need the record to be unreadable until the redaction lands.

## Choices made, and what would change them

- **The analyzer, not the anonymizer.** Presidio's anonymizer pins `cryptography` below 49, and one
  lock for every extra would have held the service on a release with six published advisories.
  Replacing a span is fifteen lines; overlapping findings become one span labelled by the most
  confident. Revisit when that pin lifts.
- **No model in the extra.** torch alone is over a gigabyte, and spaCy's models are not on PyPI. A
  configured model that is not installed is refused at start, by name. Presidio would otherwise
  try to download it during a request.
- **Redaction, not pseudonymisation.** The same person becomes `<PERSON>` every time, not a stable
  token per person. A consumer that needs to follow one person through a run needs Presidio's
  operators with a keyed hash, and a key the platform manages.
- **An LLM as the detector was not measured.** Presidio can drive one through LangExtract, and
  Willma would keep the text inside SURF. It would be slower again than GLiNER and not
  deterministic, which matters for an instrument whose name goes on the record. Measure it before
  choosing it.
- **Nothing here stops personal data reaching a model.** That is the agent's side, before the
  prompt is sent.
