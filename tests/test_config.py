from agentic_base.config import Settings, get_settings


def test_get_settings():
    settings = get_settings()

    assert settings == Settings()
