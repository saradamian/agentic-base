"""Run the redaction instrument in each mode over a small hand-written sample.

Not a benchmark: twelve sentences, English and Dutch, synthetic names, two with nothing personal
in them. It exists so the claim that a model is needed, and the choice between models, can be
rerun rather than trusted. A gold item counts as caught when its text no longer appears in the
output. Over-redaction is counted in words: a word that belongs to no gold item and that some
finding covers, so a wrong span that swallows the words beside a real name is counted too.

Needs the redaction extra, plus gliner and the two spaCy models for the model rows; a row whose
model is not installed is reported as skipped, with the reason.

    python scripts/measure_redaction.py
"""

from __future__ import annotations

import logging
import time
import warnings

from agentic_base.redaction.presidio import PresidioRedactor

GLINER = ("urchade/gliner_multi_pii-v1", "1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d")
ALLOW = ["Snellius", "LUMI", "gpu_h100", "vLLM"]

SAMPLE: list[tuple[str, list[str]]] = [
    (
        "Please forward the results to Maria Jansen at maria.jansen@example.org before Friday.",
        ["Maria Jansen", "maria.jansen@example.org"],
    ),
    (
        "Pieter van den Berg from Utrecht called about the allocation on Snellius.",
        ["Pieter van den Berg", "Utrecht"],
    ),
    ("The patient, Sophie de Wit, has BSN 111222333.", ["Sophie de Wit", "111222333"]),
    (
        "Contact Ahmed Yilmaz on +31 6 1234 5678 or at his office in Eindhoven.",
        ["Ahmed Yilmaz", "+31 6 1234 5678", "Eindhoven"],
    ),
    (
        "Transfer to IBAN NL91ABNA0417164300 in the name of Lars Bakker.",
        ["NL91ABNA0417164300", "Lars Bakker"],
    ),
    ("Run the tests in the repository and report back to Emma.", ["Emma"]),
    (
        "Stuur het rapport naar Jeroen Visser, Kerkstraat 12, Amsterdam.",
        ["Jeroen Visser", "Kerkstraat 12", "Amsterdam"],
    ),
    (
        "Mevrouw Fatima el Amrani heeft burgerservicenummer 123456782.",
        ["Fatima el Amrani", "123456782"],
    ),
    (
        "De bespreking met Tom Hendriks in Leiden is verplaatst naar dinsdag.",
        ["Tom Hendriks", "Leiden"],
    ),
    (
        "Bel Anouk de Graaf via 020-7654321 als de job op LUMI mislukt.",
        ["Anouk de Graaf", "020-7654321"],
    ),
    ("The job 12345678 failed after 7200 seconds on partition gpu_h100.", []),
    ("Zet max_model_len op 262144 en herstart de vLLM serve op node gcn42.", []),
]

MODES = {
    "patterns only": {},
    "spaCy en + nl": {
        "spacy_models": {"en": "en_core_web_lg", "nl": "nl_core_news_lg"}
    },
    "GLiNER multi PII": {"gliner_model": GLINER[0], "gliner_revision": GLINER[1]},
}


def _findings(redactor: PresidioRedactor, text: str) -> list[tuple[int, int]]:
    spans = []
    for engine, language in redactor._engines:
        for r in engine.analyze(
            text=text,
            language=language,
            entities=redactor.entities,
            allow_list=redactor.allow_list or None,
        ):
            spans.append((r.start, r.end))
    return spans


def _words(text: str) -> list[tuple[int, int]]:
    spans, start = [], None
    for i, ch in enumerate(text + " "):
        if ch.isalnum() or ch in "@.+-_":
            start = i if start is None else start
        elif start is not None:
            spans.append((start, i))
            start = None
    return spans


def main() -> None:
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    gold_total = sum(len(g) for _, g in SAMPLE)
    print(
        f"{'mode':18} {'allow-list':>10} {'caught':>8} {'words over-redacted':>20} {'ms/sentence':>12}"
    )
    for name, kwargs in MODES.items():
        for allow in ((), ALLOW):
            try:
                redactor = PresidioRedactor(allow_list=allow, **kwargs)
            except ImportError as exc:
                print(f"{name:18} skipped: {exc}")
                break
            caught = over = 0
            start = time.perf_counter()
            for text, gold in SAMPLE:
                out = redactor.redact(text).text
                caught += sum(item not in out for item in gold)
                gold_spans = [(text.index(g), text.index(g) + len(g)) for g in gold]
                found = _findings(redactor, text)
                over += sum(
                    1
                    for ws, we in _words(text)
                    if not any(ws < ge and we > gs for gs, ge in gold_spans)
                    and any(ws < fe and we > fs for fs, fe in found)
                )
            ms = (time.perf_counter() - start) * 1000 / len(SAMPLE)
            print(
                f"{name:18} {'yes' if allow else 'no':>10} {caught:>4}/{gold_total:<3} {over:>20} {ms:>12.0f}"
            )


if __name__ == "__main__":
    main()
