"""The GLiNER fallback, with a fake model: offsets, the name filter, the device, the refusal."""

from __future__ import annotations

import importlib.util

import pytest

from agentic_base.redaction.gliner import (
    GlinerDetector,
    looks_like_a_name,
    resolve_device,
)
from agentic_base.redaction.llm import DetectorUnavailable


class _FakeModel:
    """Tags every occurrence of the given words, as GLiNER returns them: offsets within the piece."""

    def __init__(self, tags: dict[str, str], fail: bool = False) -> None:
        self.tags, self.fail = tags, fail
        self.pieces: list[str] = []

    def predict_entities(self, text, labels, threshold):
        if self.fail:
            raise RuntimeError("CUDA out of memory")
        self.pieces.append(text)
        out = []
        for word, label in self.tags.items():
            start = text.find(word)
            while start != -1:
                out.append(
                    {
                        "start": start,
                        "end": start + len(word),
                        "label": label,
                        "score": 0.9,
                    }
                )
                start = text.find(word, start + 1)
        return out


def test_findings_in_later_pieces_map_back_to_their_place_in_the_whole_text() -> None:
    model = _FakeModel({"Anouk de Graaf": "person", "Utrecht": "location"})
    text = " ".join(["filler"] * 400) + " Anouk de Graaf moved to Utrecht."
    detector = GlinerDetector(
        model="m", loaded=model, chunk_words=150, overlap_words=25
    )

    spans = detector.detect(text)

    assert len(model.pieces) >= 3
    assert {(text[s.start : s.end], s.entity) for s in spans} == {
        ("Anouk de Graaf", "PERSON"),
        ("Utrecht", "LOCATION"),
    }


def test_a_role_noun_is_not_a_person() -> None:
    """GLiNER tagged "the agent" as a person above 0.9 in every piece of a technical transcript."""
    model = _FakeModel({"The agent": "person", "agent": "person", "Emma": "person"})

    spans = GlinerDetector(model="m", loaded=model).detect(
        "The agent asked Emma; the agent waited."
    )

    assert {s.entity for s in spans} == {"PERSON"} and len(spans) == 1


@pytest.mark.parametrize(
    ("found", "name"),
    [
        ("agent", False),
        ("The agent", False),
        ("de gebruiker", False),
        ("Emma", True),
        ("Pieter van den Berg", True),
        ("de Graaf", True),
    ],
)
def test_a_person_needs_a_capitalised_word_after_any_article(found, name) -> None:
    assert looks_like_a_name(found) is name


def test_a_model_failure_makes_the_detector_unavailable() -> None:
    with pytest.raises(DetectorUnavailable, match="RuntimeError"):
        GlinerDetector(model="m", loaded=_FakeModel({}, fail=True)).detect(
            "Mail Maria."
        )


def test_findings_on_masked_text_are_dropped() -> None:
    spans = GlinerDetector(model="m", loaded=_FakeModel({"####": "person"})).detect(
        "key #### here"
    )

    assert spans == []


def test_auto_picks_the_gpu_only_when_torch_sees_one() -> None:
    assert resolve_device("auto", cuda_available=True) == "cuda"
    assert resolve_device("auto", cuda_available=False) == "cpu"
    assert resolve_device("cuda:1", cuda_available=False) == "cuda:1"
    with pytest.raises(ValueError):
        resolve_device("gpu", cuda_available=True)


def test_the_instrument_names_model_revision_and_device() -> None:
    detector = GlinerDetector(
        model="org/m", revision="abc", device="cpu", loaded=_FakeModel({})
    )

    assert detector.instrument == "gliner org/m@abc on cpu"


def test_without_the_package_the_fallback_is_refused_by_name(monkeypatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "gliner" else real(name, *a),
    )

    with pytest.raises(ImportError, match="pip install gliner"):
        GlinerDetector(model="urchade/gliner_multi_pii-v1")
