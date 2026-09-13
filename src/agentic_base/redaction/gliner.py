"""Names and places found by a GLiNER PII model, on a GPU when there is one.

The fallback when the language-model endpoint cannot answer. GLiNER runs in process: no network,
no second service, the same answer for the same text. On CPU it is slow, about 250 words a
second measured, so a long transcript holds the write for minutes; on a GPU it is not.

GLiNER and torch are not dependencies of this package. torch alone is over a gigabyte, and a
deployment that never falls back should not carry it. A configured model whose package is not
installed is refused at start, by name.

A person span needs a capitalised word, because the model tags role nouns such as "the agent" as
people with high confidence, and an agent transcript is full of them.

The model reads a few hundred tokens at a time and truncates silently beyond that, so text is cut
into short overlapping pieces and the offsets mapped back.
"""

from __future__ import annotations

import importlib.util
import re
from typing import Any

from agentic_base.redaction.llm import LOCATION, PERSON, DetectorUnavailable, _pieces
from agentic_base.redaction.redact import Span

_LABELS = {"person": PERSON, "location": LOCATION, "address": LOCATION}


class GlinerDetector:
    """People and places from a GLiNER model loaded once."""

    name = "gliner"

    def __init__(
        self,
        *,
        model: str,
        revision: str = "",
        device: str = "auto",
        threshold: float = 0.3,
        chunk_words: int = 150,
        overlap_words: int = 25,
        loaded: Any = None,
    ) -> None:
        self.model_name = model
        self.revision = revision
        self._threshold = threshold
        self._chunk = chunk_words
        self._overlap = overlap_words
        if loaded is not None:
            self._model, self.device = loaded, device if device != "auto" else "cpu"
            return
        if (
            importlib.util.find_spec("gliner") is None
            or importlib.util.find_spec("torch") is None
        ):
            raise ImportError(
                f"the GLiNER fallback {model} needs the gliner and torch packages: pip install gliner"
            )
        import torch
        from gliner import GLiNER

        self.device = resolve_device(device, torch.cuda.is_available())
        kwargs = {"revision": revision} if revision else {}
        self._model = GLiNER.from_pretrained(model, map_location=self.device, **kwargs)

    @property
    def instrument(self) -> str:
        return (
            f"gliner {self.model_name}@{self.revision or 'unpinned'} on {self.device}"
        )

    def available(self) -> bool:
        return True

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for start, end in _pieces(text, self._chunk, self._overlap):
            chunk = text[start:end]
            try:
                entities = self._model.predict_entities(
                    chunk, list(_LABELS), threshold=self._threshold
                )
            except (
                Exception
            ) as exc:  # the model is a black box; any failure means no answer
                raise DetectorUnavailable(
                    f"GLiNER failed: {type(exc).__name__}"
                ) from None
            for e in entities:
                label = _LABELS.get(str(e.get("label", "")).lower())
                found = chunk[e["start"] : e["end"]]
                if not label or "#" in found:
                    continue
                if label == PERSON and not looks_like_a_name(found):
                    continue
                score = float(e.get("score", 0.5))
                spans.append(Span(start + e["start"], start + e["end"], label, score))
        return spans


_ARTICLES = frozenset(
    {"the", "a", "an", "de", "het", "een", "die", "dat", "this", "that"}
)


def looks_like_a_name(found: str) -> bool:
    """Whether a person span has a capitalised word after any leading article.

    GLiNER tags role nouns as people with high confidence: "the agent" scored above 0.9 in every
    piece of a technical transcript, and a higher threshold did not remove it. Names are
    capitalised in English and Dutch. The cost is that a name typed all in lower case is missed
    by the fallback; the language model does not have this filter.
    """
    words = found.split()
    while words and words[0].casefold() in _ARTICLES:
        words = words[1:]
    return any(w[:1].isupper() for w in words)


def resolve_device(device: str, cuda_available: bool) -> str:
    """``auto`` means the GPU when torch can see one, the CPU otherwise."""
    if device == "auto":
        return "cuda" if cuda_available else "cpu"
    if not re.fullmatch(r"cpu|cuda(:\d+)?", device):
        raise ValueError(f"device must be auto, cpu or cuda[:N], not {device!r}")
    return device
