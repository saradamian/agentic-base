"""Run each redaction mode over a small hand-written sample, and over one long message.

Not a benchmark: twelve sentences, English and Dutch, synthetic names, two with nothing personal
in them. It exists so the choice of detectors can be rerun rather than trusted. A gold item counts
as caught when its text no longer appears in the output; over-redaction is counted in words that
belong to no gold item and were removed anyway.

    python scripts/measure_redaction.py                      # patterns only
    REDACTION_LLM_URL=... REDACTION_LLM_API_KEY=... REDACTION_LLM_MODEL=... \
    REDACTION_GLINER_MODEL=urchade/gliner_multi_pii-v1 REDACTION_GLINER_REVISION=... \
        python scripts/measure_redaction.py

A mode whose settings or packages are missing is reported as skipped, with the reason.
"""

from __future__ import annotations

import os
import re
import time

from agentic_base.redaction.layered import LayeredRedactor

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


FILLER = (
    "The agent rebuilt the environment on Snellius and resubmitted the job to partition "
    "gpu_h100 after raising max_model_len to 262144. "
)


def _words(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in re.finditer(r"[\w@.+-]+", text)]


def _removed_outside_gold(text: str, out: str, gold: list[str]) -> int:
    kept = set(out.split())
    gold_spans = [(text.index(g), text.index(g) + len(g)) for g in gold]
    return sum(
        1
        for a, b in _words(text)
        if not any(a < ge and b > gs for gs, ge in gold_spans)
        and text[a:b] not in kept
        and text[a:b].strip(".,;") not in {w.strip(".,;") for w in kept}
    )


def _modes() -> dict[str, object]:
    modes: dict[str, object] = {
        "patterns only": lambda: LayeredRedactor(allow_list=ALLOW)
    }
    url, key, model = (
        os.environ.get(f"REDACTION_LLM_{k}", "") for k in ("URL", "API_KEY", "MODEL")
    )
    if url and key and model:
        from agentic_base.redaction.llm import LlmDetector

        modes["language model"] = lambda: LayeredRedactor(
            primary=LlmDetector(
                base_url=url, api_key=key, model=model, chunk_words=600
            ),
            allow_list=ALLOW,
        )
    else:
        modes["language model"] = (
            "set REDACTION_LLM_URL, REDACTION_LLM_API_KEY, REDACTION_LLM_MODEL"
        )
    gliner_model = os.environ.get("REDACTION_GLINER_MODEL", "")
    if gliner_model:
        from agentic_base.redaction.gliner import GlinerDetector

        revision = os.environ.get("REDACTION_GLINER_REVISION", "")
        modes["GLiNER"] = lambda: LayeredRedactor(
            primary=GlinerDetector(model=gliner_model, revision=revision),
            allow_list=ALLOW,
        )
    else:
        modes["GLiNER"] = "set REDACTION_GLINER_MODEL"
    return modes


def main() -> None:
    total = sum(len(g) for _, g in SAMPLE)
    long_text = " ".join(FILLER * 10 + text for text, _ in SAMPLE)
    long_gold = sorted({g for _, gs in SAMPLE for g in gs})
    print(
        f"{'mode':16} {'caught':>7} {'over':>5} {'s/sentence':>10} {'long message':>28}"
    )
    for name, build in _modes().items():
        if isinstance(build, str):
            print(f"{name:16} skipped: {build}")
            continue
        try:
            redactor = build()
        except ImportError as exc:
            print(f"{name:16} skipped: {exc}")
            continue
        caught = over = 0
        start = time.perf_counter()
        for text, gold in SAMPLE:
            out = redactor.redact(text).text
            caught += sum(item not in out for item in gold)
            over += _removed_outside_gold(text, out, gold)
        per = (time.perf_counter() - start) / len(SAMPLE)
        start = time.perf_counter()
        long_out = redactor.redact(long_text).text
        missed = sum(g in long_out for g in long_gold)
        words = len(long_text.split())
        long_s = time.perf_counter() - start
        print(
            f"{name:16} {caught:>3}/{total:<3} {over:>5} {per:>10.2f} {f'{words} words, {long_s:.1f}s, missed {missed}':>28}"
        )


if __name__ == "__main__":
    main()
