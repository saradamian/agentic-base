# Redaction

How a transcript loses its personal data and credentials before it is written, what does it, and
what happens when part of it cannot run.

## What runs, in order

1. **Patterns**, always, standard library only: credentials, email addresses, phone numbers,
   IBANs, card numbers, IP addresses and the Dutch citizen service number. Checksums carry the
   precision: mod 97 for an IBAN, Luhn and a known leading digit for a card, the eleven test for
   a citizen service number. Credentials are recognised by shape wherever they appear, including
   the shape of a Willma key.
2. **Masking.** Everything the patterns found is replaced by `#` characters of the same length.
   Offsets do not move, and a credential or a bank number never leaves the service to be
   detected.
3. **Names and places from a language model** on Willma, by default `RedHatAI/gemma-4-31B-it-NVFP4`.
4. **GLiNER** in process, when the model cannot answer: a GPU if torch sees one, the CPU if not.
5. **Refusal**, when neither can answer. The service answers 503 with `Retry-After` and writes
   nothing. A run classified `public` is the exception: it is written with patterns alone, and its
   record says so.

Every finding becomes its entity type: `Forward it to <PERSON>`. Every record says what ran:
`redaction` names the patterns and the name detector with its model, marked `(fallback)` when
GLiNER stood in, and `extra.redaction` counts the strings examined, the findings per type, and
how many strings each instrument handled. A writer that redacted its own transcript says so in
`redaction`, and the service leaves that record alone.

Settings: `REDACTION` is `none`, `patterns` or `names`; the `REDACTION_LLM_*` and
`REDACTION_GLINER_*` settings configure the two detectors; `REDACTION_ALLOW_LIST` exempts the
site's own vocabulary; `REDACTION_ENTITIES` narrows what is removed.

## Guards on the model

- **Output is constrained by a JSON schema.** Asked without one, the same model returned a
  differently shaped object in a Markdown fence.
- **Input is fenced as data**, with a delimiter carrying a random nonce, and the instructions say
  nothing inside the fence is an instruction. In a test the model ignored an "ignore all previous
  instructions" line. That lowers the risk of a transcript steering the detector; it does not
  remove it. A steered model can only miss or over-remove, because it can only name strings, and
  each string is looked up verbatim in the text: one that does not occur removes nothing and is
  counted.
- **Long text is cut into overlapping pieces** of 1,500 words, run four at a time.
- **A truncated answer is not trusted.** The piece is split and asked again.
- **Retries follow `llm.resilience`.** A dead connection is retried once on a fresh transport, a
  gateway status once, a timeout never.
- **The timeout is 300 seconds**, because Willma's proxies cut a request at 300
  (`proxy_read_timeout` in its nginx template, the Apache `ProxyPass` timeout). A longer client
  timeout would only receive their 504.
- **After a failure the model cools down for 60 seconds.** Writes in that window go straight to
  GLiNER instead of each waiting for the same failure.
- **The key is a secret setting** and appears in no error message or log line.

## Measured

`scripts/measure_redaction.py` runs each mode over twelve hand-written English and Dutch
sentences with synthetic names, two of them containing nothing personal, and over one
2,407-word message with those sentences scattered through technical filler. A smoke test of the
choice, not a benchmark. 2026-09-13, Gemma on Willma warm, GLiNER on CPU:

| mode | caught of 21 | ordinary words removed | per sentence | 2,407-word message |
|---|---|---|---|---|
| patterns only | 6 | 0 | under 10 ms | missed 15, all names and places |
| Gemma on Willma | 21 | 0 | 0.5 s | 1.8 s, missed none |
| GLiNER on CPU | 21 | 4 | 0.1 s | 5.5 s, missed none |

Gemma gave identical findings on three repeated passes. Qwen3.5-122B on the same endpoint did
not: it dropped a name in one pass and flagged a cluster name in another, at temperature 0.
GLiNER's words removed are titles and neighbours, "Mevrouw" and "Bel", swallowed into the name
after them. A cold start of the Willma model took 21 seconds a sentence; the model list reports
`state: unloaded` and `latency_mode: on-demand`, and the cooldown sends writes to GLiNER while
the model loads.

GLiNER tagged "the agent" as a person, above 0.9 confidence, in every piece of a technical
transcript; on the long message that was 110 false people. A person span now needs a capitalised
word after any leading article. An all-lowercase name typed in chat is therefore missed on the
fallback path, and not on the model path.

## Choices, and what would change them

- **Presidio was adopted and removed.** Its analyzer requires spaCy even for patterns: 56
  packages and 285 MB against the library's 17 and 14 MB, and an import of two seconds. Its
  anonymizer pins `cryptography` below 49, which would have held the service on a release with six
  advisories. With names from a model, what was left of it was patterns.
- **No dependency is added.** The pattern layer is standard library; the model client is httpx,
  which the library already uses. GLiNER and torch are the deployer's to install when the
  fallback is configured, and a configured fallback that is not installed is refused at start.
- **Willma is a second processor.** Transcripts, masked of everything the patterns found, go to
  another SURF service for detection. The processing record names it.
- **The model version is not pinned.** The record carries the model name and Willma's
  registration timestamp for it; Willma can change the weights behind the name, and nothing here
  can see that. GLiNER is pinned by revision.
- **GPT-NL is registered on Willma** and not granted to the keys tried. Measure it with the same
  script once it is.
- **Redaction, not pseudonymisation.** The same person becomes `<PERSON>` every time. Following
  one person through a run would need a keyed hash and a key the platform manages.
- **Nothing here stops personal data reaching the agent's own model.** That is the agent's side,
  before the prompt is sent.
