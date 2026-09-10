"""Cluster profiles load, and refuse to carry secrets."""

import pytest

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
