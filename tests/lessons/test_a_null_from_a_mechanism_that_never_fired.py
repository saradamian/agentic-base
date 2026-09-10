"""Why an unmeasured retrieval layer can return a confident null.

Self-contained on purpose: no framework, no imports beyond the standard library. The defect is
one line of arithmetic in a similarity normaliser, and the consequence is that an ablation
reports 0.0 from a mechanism that never fired.

This is here as a lesson rather than as a test of this project's code. It runs in CI so it cannot
rot, and it is the shortest demonstration of the failure this whole project exists to catch: a
clean zero that reads exactly like a finding.

Measured equivalents from the project this came from: a 697-token human-authored entry scored
0.0206 for a real task prompt against a 0.1 floor, while a shorter and less relevant entry scored
0.0443 and ranked above it.
"""

from __future__ import annotations

FLOOR = 0.1
"""Candidates below this are discarded before use."""


def jaccard(query: set[str], entry: set[str]) -> float:
    """Normalise by the union, so the entry's own length sits in the denominator."""
    return len(query & entry) / len(query | entry)


def coverage(query: set[str], entry: set[str]) -> float:
    """Normalise by the query. Length-independent."""
    return len(query & entry) / len(query)


def _tokens(n: int, prefix: str) -> set[str]:
    return {f"{prefix}{i}" for i in range(n)}


def test_a_thorough_entry_cannot_clear_the_floor_under_union_normalisation() -> None:
    """A short query fully contained in a long entry is a perfect match and still scores 0.03."""
    query = _tokens(20, "q")
    entry = query | _tokens(680, "e")

    assert jaccard(query, entry) < FLOOR
    assert coverage(query, entry) == 1.0


def test_a_thinner_less_relevant_entry_outranks_a_thorough_relevant_one() -> None:
    """The ranking inverts too, which is the self-reinforcing half of the defect."""
    query = _tokens(20, "q")
    thorough = _tokens(20, "q") | _tokens(680, "e")
    thin = _tokens(10, "q") | _tokens(30, "e")

    assert jaccard(query, thin) > jaccard(query, thorough)
    assert coverage(query, thorough) > coverage(query, thin)


def test_an_ablation_over_this_scorer_reports_a_null_from_nothing_firing() -> None:
    """The reason it belongs here and not in a list of retrieval bugs.

    With nothing clearing the floor the treatment arm uses nothing, so treatment and control are
    the same configuration and the contrast is exactly zero. That is indistinguishable from the
    feature not helping, and it is wrong.
    """
    query = _tokens(20, "q")
    library = [_tokens(20, "q") | _tokens(n, "e") for n in (300, 500, 680)]

    retrieved = [entry for entry in library if jaccard(query, entry) >= FLOOR]

    assert retrieved == [], "nothing is retrievable, so the arms are identical"
