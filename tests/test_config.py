from agentic_base.config import Settings, get_settings


def test_get_settings():
    settings = get_settings()

    assert settings == Settings()


def test_the_suite_never_opens_the_database_in_the_working_directory() -> None:
    """The default file is `./agentic-base.db`. A suite that writes it leaves a schema behind,
    and the next run fails with `no column named ...`, which reads like a code regression and is
    not one. Continuous integration never sees it, because its container is fresh."""
    url = get_settings().database_url

    assert url.startswith("sqlite:///")
    assert not url.endswith("agentic-base.db"), (
        "conftest should point the service at a tmp file"
    )
