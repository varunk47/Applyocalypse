"""Tests for secret_env.py — file-based secret handoff with env-var fallback."""
from __future__ import annotations

import json
import os

import pytest

from applyocalypse_automation.secret_env import _secrets_from_file, get_secret


@pytest.fixture(autouse=True)
def clear_lru_cache():
    """Clear the lru_cache on _secrets_from_file before each test."""
    _secrets_from_file.cache_clear()
    yield
    _secrets_from_file.cache_clear()


class TestSecretsFromFile:
    def test_file_present_key_present_returns_file_value(self, tmp_path, monkeypatch):
        secrets = {"APPLYO_APPLICATION_PASSWORD": "s3cr3t"}
        secret_file = tmp_path / "worker-secrets.json"
        secret_file.write_text(json.dumps(secrets), encoding="utf-8")
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(secret_file))
        monkeypatch.setenv("APPLYO_APPLICATION_PASSWORD", "env-value")

        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result == "s3cr3t"

    def test_file_value_wins_over_env(self, tmp_path, monkeypatch):
        secrets = {"APPLYO_APPLICATION_PASSWORD": "file-wins"}
        secret_file = tmp_path / "worker-secrets.json"
        secret_file.write_text(json.dumps(secrets), encoding="utf-8")
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(secret_file))
        monkeypatch.setenv("APPLYO_APPLICATION_PASSWORD", "env-value")

        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result == "file-wins"

    def test_secrets_file_unset_falls_back_to_env(self, monkeypatch):
        monkeypatch.delenv("APPLYO_SECRETS_FILE", raising=False)
        monkeypatch.setenv("APPLYO_APPLICATION_PASSWORD", "from-env")

        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result == "from-env"

    def test_file_path_set_but_file_missing_falls_back_to_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(tmp_path / "does-not-exist.json"))
        monkeypatch.setenv("APPLYO_APPLICATION_PASSWORD", "fallback")

        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result == "fallback"

    def test_file_path_set_but_corrupt_json_falls_back_to_env(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "worker-secrets.json"
        secret_file.write_text("NOT VALID JSON {{{", encoding="utf-8")
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(secret_file))
        monkeypatch.setenv("APPLYO_APPLICATION_PASSWORD", "fallback-on-corrupt")

        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result == "fallback-on-corrupt"

    def test_corrupt_json_does_not_raise(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "worker-secrets.json"
        secret_file.write_text("NOT VALID JSON", encoding="utf-8")
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(secret_file))

        # Should not raise
        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result is None

    def test_missing_file_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(tmp_path / "missing.json"))

        # Should not raise
        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result is None

    def test_key_absent_from_file_and_env_returns_none(self, tmp_path, monkeypatch):
        secrets = {"SOME_OTHER_KEY": "value"}
        secret_file = tmp_path / "worker-secrets.json"
        secret_file.write_text(json.dumps(secrets), encoding="utf-8")
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(secret_file))
        monkeypatch.delenv("APPLYO_APPLICATION_PASSWORD", raising=False)

        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result is None

    def test_otp_password_from_file(self, tmp_path, monkeypatch):
        secrets = {"APPLYO_GMAIL_OTP_PASSWORD": "otp-pass"}
        secret_file = tmp_path / "worker-secrets.json"
        secret_file.write_text(json.dumps(secrets), encoding="utf-8")
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(secret_file))

        result = get_secret("APPLYO_GMAIL_OTP_PASSWORD")

        assert result == "otp-pass"

    def test_non_dict_json_falls_back_to_env(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "worker-secrets.json"
        secret_file.write_text(json.dumps(["list", "not", "dict"]), encoding="utf-8")
        monkeypatch.setenv("APPLYO_SECRETS_FILE", str(secret_file))
        monkeypatch.setenv("APPLYO_APPLICATION_PASSWORD", "fallback-list")

        result = get_secret("APPLYO_APPLICATION_PASSWORD")

        assert result == "fallback-list"
