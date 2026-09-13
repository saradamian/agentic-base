"""The repository is public. Site facts and internal sources stay out of it.

Two layers. The deployment side checks the site's own identifiers against a private list in the
overlay (`.overlay/forbidden.txt`), which is deliberately not here: a list of what a site hides
describes the site. This test is the upstream layer and it works by SHAPE, not by word, because
a word list only ever catches what its author already thought of:

* a URL whose host is not on the short list of public hosts this project cites;
* an email address, other than the noreply identity commits carry;
* an absolute path under a home directory;
* an IP address outside the documentation and loopback ranges;
* attribution to a source a reader cannot open.

Names of people are not detectable by shape and are the private list's job, or a person's.
Every detector below was planted against and watched to fail before it was trusted.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Hosts a public page may link to. Adding one is a review decision, which is the point.
PUBLIC_HOSTS = {
    "github.com",
    "pypi.org",
    "pypi.python.org",
    "python.org",
    "docs.python.org",
    "peps.python.org",
    "w3id.org",
    "www.w3.org",
    "openlineage.io",
    "www.researchobject.org",
    "opentelemetry.io",
    "mlflow.org",
    "modelcontextprotocol.io",
    "blog.modelcontextprotocol.io",
    "docs.pypi.org",
    "img.shields.io",
    "schema.org",
    "json-schema.org",
    "cloud.langfuse.com",
    "www.iaasb.org",
    "eur-lex.europa.eu",
    "artificialintelligenceact.eu",
    "easybuild.io",
    "restrictedpython.readthedocs.io",
    "www.contributor-covenant.org",
    "docs.pytest.org",
    "fastapi.tiangolo.com",
    "stackoverflow.com",
    "semver.org",
}

#: Reserved for documentation and tests, by RFC 2606 and RFC 6761: any host under these.
RESERVED_SUFFIXES = (
    ".example.com",
    ".example.org",
    ".example.net",
    ".example",
    ".test",
    ".invalid",
    ".localhost",
)


def _public(host: str) -> bool:
    """A host a public page may name: on the list, reserved for examples, or a bare label with
    no dot, which is a test fixture or a container name and resolves nowhere."""
    return (
        host in PUBLIC_HOSTS
        or host in {"example.com", "example.org", "example.net", "localhost"}
        or host.endswith(RESERVED_SUFFIXES)
        or "." not in host
    )


#: Hostnames that appear in examples and configuration by design.
EXAMPLE_HOSTS = {
    "otel-collector",
    "phoenix",
    "collector",
    "x",
    "gpu",
    "slurmrestd",
    "localhost",
}

URL = re.compile(r"https?://([A-Za-z0-9.-]+)(?::\d+)?[/\s)\]>\"'`]?")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATH = re.compile(r"/(home|Users)/[A-Za-z0-9._-]+")
# Not preceded or followed by a path or version character, so `cuDNN/9.10.1.4-CUDA` is a version.
IPV4 = re.compile(r"(?<![\w/.-])(\d{1,3}\.){3}\d{1,3}(?![\w.-])")
SOURCE_WORDS = re.compile(
    r"internal (wiki|gitlab|registry|documentation)|design memo|user interviews?|\bCISO\b"
)
ALLOWED_EMAIL_HOSTS = {
    "users.noreply.github.com",
    "example.org",
    "example.com",
    "noreply.invalid",
}
ALLOWED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("93.184.216.0/24"),  # example.com
    ipaddress.ip_network("1.2.3.0/24"),  # the obviously fake one the tests use
    ipaddress.ip_network(
        "10.0.0.0/8"
    ),  # private ranges are what the SSRF tests assert on
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
]

FILES = [
    *ROOT.glob("*.md"),
    *ROOT.glob("*.cff"),
    *ROOT.glob("*.toml"),
    *ROOT.glob("*.yml"),
    *ROOT.glob("*.yaml"),
    *(ROOT / "docs").rglob("*.md"),
    *(ROOT / "docs").rglob("*.json"),
    *(ROOT / "src").rglob("*.py"),
    *(ROOT / "src").rglob("*.yaml"),
    *(ROOT / "tests").rglob("*.py"),
    *(ROOT / "scripts").rglob("*.py"),
    *(ROOT / ".github").rglob("*.yml"),
    *(ROOT / "charts").rglob("*.yaml"),
]


def _findings(text: str) -> list[str]:
    out = []
    for m in URL.finditer(text):
        host = m.group(1).lower().rstrip(".")
        if not _public(host) and not _is_ip(host):
            out.append(f"url host {host}")
    for m in EMAIL.finditer(text):
        if m.group(0).split("@")[1].lower() not in ALLOWED_EMAIL_HOSTS:
            out.append(f"email {m.group(0)}")
    for m in HOME_PATH.finditer(text):
        out.append(f"home path {m.group(0)}")
    for m in IPV4.finditer(text):
        if _is_ip(m.group(0)) and not any(
            ipaddress.ip_address(m.group(0)) in n for n in ALLOWED_IP_NETWORKS
        ):
            out.append(f"ip {m.group(0)}")
    for m in SOURCE_WORDS.finditer(text):
        out.append(f"internal source {m.group(0)}")
    return out


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def test_public_files_carry_no_private_host_address_path_or_source() -> None:
    hits = []
    for path in FILES:
        if path.name == "test_public_hygiene.py":
            continue
        text = path.read_text(errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for finding in _findings(line):
                hits.append(f"{path.relative_to(ROOT)}:{line_no}: {finding}")
    assert len(FILES) > 60, (
        f"only {len(FILES)} files listed; the file list is not the repository"
    )
    assert not hits, (
        f"{len(FILES)} files read; {len(hits)} findings:\n  " + "\n  ".join(hits)
    )


def test_each_detector_fires_on_a_planted_example() -> None:
    """The guard is only worth its green if each shape has been seen to go red."""
    planted = {
        "a url": "see https://wiki.some-institute.net/x",
        "an email": "mail alice@some-institute.example",
        "a home path": "logs in /home/someone/run.log",
        "an ip": "the box at 145.100.1.1",
        "a source word": "as the design memo says",
    }
    for what, text in planted.items():
        assert _findings(text), f"{what} was planted and not detected"
    assert (
        _findings(
            "see https://github.com/x and 127.0.0.1 and noreply@users.noreply.github.com"
        )
        == []
    )
