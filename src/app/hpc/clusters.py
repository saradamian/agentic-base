"""Cluster profiles.

A profile is data: the facts about a cluster that its scheduler cannot report about itself, plus
the names of the environment variables that supply its credentials. No secret ever appears in a
profile, and a profile that contains one is a defect.

Precedence runs low to high: built-in defaults, the profile file, environment variables, and
then whatever a caller passes explicitly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROFILE_DIR = Path(__file__).resolve().parents[3] / "config" / "clusters"

SECRET_MARKERS = ("token", "password", "secret", "key")
"""Substrings that suggest a value rather than a variable name has been pasted into a profile."""


class ProfileError(Exception):
    """A profile is missing, malformed, or contains something it must not."""


@dataclass(frozen=True)
class ClusterProfile:
    name: str
    description: str
    backend: str
    ssh_host: str
    login_hosts: list[str]
    partitions: dict[str, Any]
    hardware: dict[str, Any]
    storage: dict[str, Any]
    containers: dict[str, Any]
    serving: dict[str, Any]
    energy: dict[str, Any]
    limits: dict[str, Any]
    credentials: dict[str, str] = field(default_factory=dict)

    @property
    def gpu_vendor(self) -> str:
        return str(self.hardware.get("gpu_vendor", "unknown"))

    @property
    def needs_container(self) -> bool:
        return bool(self.containers.get("runtime"))

    @property
    def user_namespaces_available(self) -> bool:
        return bool(self.containers.get("user_namespaces_available", False))

    def credential(self, purpose: str) -> str | None:
        """Read a credential from the environment variable the profile names for it.

        Returns None when the variable is unset, so a caller can report which variable is missing
        rather than failing with an empty string.
        """
        variable = self.credentials.get(purpose)
        if not variable:
            return None
        return os.environ.get(variable)

    def missing_credentials(self) -> list[str]:
        """Variable names the profile expects and the environment does not supply."""
        return [
            variable
            for variable in self.credentials.values()
            if variable and not os.environ.get(variable)
        ]

    def expand(self, value: str) -> str:
        """Expand environment references in a path from the profile."""
        return os.path.expandvars(value)


def _assert_no_secrets(raw: dict[str, Any], source: Path) -> None:
    """Reject a profile whose credentials block holds anything but variable names.

    A variable name is upper case with underscores. Anything longer or mixed case is far more
    likely to be a pasted value, and a profile is committed.
    """
    credentials = raw.get("credentials") or {}
    for purpose, value in credentials.items():
        text = str(value)
        if not text.replace("_", "").isalnum() or text != text.upper() or len(text) > 64:
            raise ProfileError(
                f"{source}: credentials.{purpose} looks like a value rather than the name of an "
                f"environment variable. Profiles are committed and must never carry secrets."
            )


def load_profile(name_or_path: str, *, profile_dir: Path | None = None) -> ClusterProfile:
    """Load a profile by name from the profile directory, or from an explicit path."""
    candidate = Path(name_or_path)
    if not candidate.suffix:
        candidate = (profile_dir or DEFAULT_PROFILE_DIR) / f"{name_or_path}.yaml"
    if not candidate.is_file():
        raise ProfileError(f"no cluster profile at {candidate}")

    raw = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ProfileError(f"{candidate}: profile must be a mapping")
    _assert_no_secrets(raw, candidate)

    try:
        return ClusterProfile(
            name=raw["name"],
            description=raw.get("description", ""),
            backend=raw.get("backend", "ssh"),
            ssh_host=raw.get("ssh_host", ""),
            login_hosts=list(raw.get("login_hosts") or []),
            partitions=raw.get("partitions") or {},
            hardware=raw.get("hardware") or {},
            storage=raw.get("storage") or {},
            containers=raw.get("containers") or {},
            serving=raw.get("serving") or {},
            energy=raw.get("energy") or {},
            limits=raw.get("limits") or {},
            credentials=raw.get("credentials") or {},
        )
    except KeyError as exc:
        raise ProfileError(f"{candidate}: missing required field {exc}") from exc


def available_profiles(profile_dir: Path | None = None) -> list[str]:
    """Names of the profiles on disk."""
    directory = profile_dir or DEFAULT_PROFILE_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))
