"""The secret scan in continuous integration, and the one rule it adds to gitleaks.

gitleaks knows provider shapes. A key issued by a site's own service matches none of them:
planting one beside an AWS key, gitleaks reported only the AWS key. The rule that closes it is a
credential pattern this package already redacts from transcripts, so the copy in `.gitleaks.toml`
is held to the module rather than maintained twice.
"""

from __future__ import annotations

import re
from pathlib import Path

from agentic_base.redaction.patterns import CREDENTIAL, PatternDetector

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".gitleaks.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "supply-chain.yml"
KEY = "77696c6c6d61" + "-0123abcd-0aec-4df0-93f0-" + "0123456789ab"


def _rule_regex() -> str:
    match = re.search(r"regex = '''(.+?)'''", CONFIG.read_text())
    assert match, "no rule regex in .gitleaks.toml"
    return match.group(1)


def test_the_added_rule_is_the_modules_own_pattern() -> None:
    """Two copies of a regular expression drift. This one cannot."""
    module = ROOT / "src" / "agentic_base" / "redaction" / "patterns.py"

    assert _rule_regex() in module.read_text()


def test_the_added_rule_matches_that_shape_and_not_a_uuid_or_a_commit() -> None:
    rule = re.compile(_rule_regex())

    assert rule.search(f"AGENTIC_LLM_API_KEY={KEY}")
    assert not rule.search("run 0123abcd-0aec-4df0-93f0-0123456789ab")
    assert not rule.search("commit 1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d")


def test_the_same_shape_is_redacted_from_a_transcript() -> None:
    assert [s.entity for s in PatternDetector().detect(f"export KEY={KEY}")] == [
        CREDENTIAL
    ]


def test_the_scan_reads_the_added_rule_and_the_whole_history() -> None:
    """A scan of the working tree alone misses a credential committed and then removed."""
    workflow = WORKFLOW.read_text()

    assert "fetch-depth: 0" in workflow
    assert "gitleaks git . --config .gitleaks.toml" in workflow
    assert "gitleaks dir . --config .gitleaks.toml" in workflow
