"""Cluster profiles load, and refuse to carry secrets."""

import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # the consumer floor; see tests/test_portable_surface.py
    import tomli as tomllib

from app.hpc import clusters
from app.hpc.clusters import ProfileError, available_profiles, load_profile


def test_both_clusters_have_a_profile() -> None:
    assert {"snellius", "lumi"} <= set(available_profiles())


def test_snellius_is_an_nvidia_cluster_without_usable_containers() -> None:
    profile = load_profile("snellius")

    assert profile.gpu_vendor == "nvidia"
    assert not profile.user_namespaces_available
    assert not profile.needs_container


def test_lumi_is_an_amd_cluster_that_requires_a_container() -> None:
    profile = load_profile("lumi")

    assert profile.gpu_vendor == "amd"
    assert profile.needs_container
    assert profile.containers["gpu_flag"] == "--rocm"


def test_lumi_runs_containers_without_user_namespaces_so_images_are_sandboxes() -> None:
    profile = load_profile("lumi")

    assert not profile.user_namespaces_available
    assert profile.containers["image_kind"] == "sandbox"


def test_a_profile_names_credentials_and_never_holds_them(tmp_path) -> None:
    for name in ("snellius", "lumi"):
        profile = load_profile(name)
        for variable in profile.credentials.values():
            assert variable == variable.upper()


def test_a_profile_that_pastes_a_secret_is_rejected(tmp_path) -> None:
    """Profiles are committed, so this has to fail loudly rather than quietly work."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: bad\ncredentials:\n  hf_token: hf_liveSecretValue123\n", encoding="utf-8"
    )

    with pytest.raises(ProfileError, match="never carry secrets"):
        load_profile(str(bad))


def test_a_missing_credential_is_reported_by_variable_name(monkeypatch) -> None:
    monkeypatch.delenv("SNELLIUS_HF_TOKEN", raising=False)
    profile = load_profile("snellius")

    assert "SNELLIUS_HF_TOKEN" in profile.missing_credentials()
    assert profile.credential("hf_token") is None


def test_an_unknown_profile_is_reported_with_the_path_it_looked_for() -> None:
    with pytest.raises(ProfileError, match="no cluster profile"):
        load_profile("does-not-exist")


def test_every_bundled_profile_sits_inside_the_package_so_a_wheel_carries_it() -> None:
    """A profile outside the package directory cannot ship, and fails only once installed.

    The previous location resolved through `parents[3]`: the repository root in a source tree,
    the parent of `site-packages` in an installed one. The suite passed, every import succeeded,
    and `load_profile` raised for every name on any installed copy.
    """
    package_root = Path(clusters.__file__).resolve().parent

    for name in available_profiles():
        path = clusters.default_profile_dir() / f"{name}.yaml"
        assert path.is_file(), f"{name} is listed but absent"
        assert package_root in path.parents, (
            f"{path} is outside {package_root}, so no wheel will carry it"
        )


def _repo_root() -> Path:
    """Walk up from this test file until pyproject.toml appears.

    Deliberately not a fixed number of `parents`, and deliberately anchored on the test rather
    than on the installed module. Counting parents is what shipped the bug this file guards
    against: the same expression resolved to the repository root in a source tree and to the
    parent of site-packages once installed, and nothing failed until somebody called a function.
    """
    for candidate in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError(
        "no pyproject.toml above this test; run the suite from a source tree"
    )


def test_the_build_declares_the_profiles_as_package_data() -> None:
    """Naming the directory is not enough; a wheel ships no non-Python file unless it is listed."""
    config = tomllib.loads(
        (_repo_root() / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_data = config["tool"]["setuptools"]["package-data"]

    assert any(
        pattern.endswith("profiles/*.yaml")
        for pattern in package_data.get("app.hpc", [])
    ), "app.hpc package-data does not carry profiles/*.yaml"


def test_a_site_can_point_the_lookup_at_its_own_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Site-specific values belong outside the artifact, so the bundled pair are examples."""
    (tmp_path / "ourcluster.yaml").write_text("name: ourcluster\n", encoding="utf-8")
    monkeypatch.setenv("AB_PROFILE_DIR", str(tmp_path))

    assert available_profiles() == ["ourcluster"]
    assert load_profile("ourcluster").name == "ourcluster"
