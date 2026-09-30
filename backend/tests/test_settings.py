"""Settings parsing that production depends on."""

from __future__ import annotations

import pytest

from app.config.settings import Settings


def make_settings(**overrides: object) -> Settings:
    # _env_file=None: never read backend/.env. Explicit arguments also beat any
    # environment variable, so the test sees only what it sets.
    overrides.setdefault("environment", "development")
    return Settings(_env_file=None, **overrides)


class TestCorsOriginList:
    def test_matches_the_form_browsers_send(self):
        """Browsers send the Origin lowercase and without a trailing slash, and
        the CORS match is exact — so a capitalised GitHub username would
        otherwise block every request from the real site."""
        settings = make_settings(cors_origins="https://Shreyas310805.github.io/")
        assert settings.cors_origin_list == ["https://shreyas310805.github.io"]

    def test_splits_trims_and_drops_empty_entries(self):
        settings = make_settings(
            cors_origins=" HTTP://LOCALHOST:3000/ ,, https://Example.GitHub.io ,"
        )
        assert settings.cors_origin_list == [
            "http://localhost:3000",
            "https://example.github.io",
        ]

    def test_production_accepts_a_mixed_case_origin(self):
        settings = make_settings(
            environment="production",
            database_url="postgresql://user:PASSWORD@db.example.invalid:5432/postgres",
            cors_origins="https://Shreyas310805.github.io",
        )
        assert settings.cors_origin_list == ["https://shreyas310805.github.io"]

    def test_production_still_rejects_a_wildcard(self):
        with pytest.raises(ValueError, match="must not contain"):
            make_settings(
                environment="production",
                database_url="postgresql://user:PASSWORD@db.example.invalid:5432/postgres",
                cors_origins="*",
            )


class TestApiKeyHygiene:
    """A key pasted with a trailing newline broke every request and leaked
    through the resulting error message; it must be trimmed on load."""

    FAKE_KEY = "sk-" + "or-v1-" + "0123456789abcdef" * 4

    def test_argument_is_trimmed(self):
        settings = make_settings(openrouter_api_key=f" {self.FAKE_KEY}\n")
        assert settings.openrouter_api_key == self.FAKE_KEY

    def test_environment_variable_is_trimmed(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", f"{self.FAKE_KEY}\r\n")
        monkeypatch.setenv("OPENAI_API_KEY", f"\t{self.FAKE_KEY}\n")
        settings = Settings(_env_file=None, environment="development")
        assert settings.openrouter_api_key == self.FAKE_KEY
        assert settings.openai_api_key == self.FAKE_KEY

    def test_whitespace_only_key_counts_as_unset(self):
        assert make_settings(openrouter_api_key=" \n").openrouter_api_key is None
