from app.core import config


def test_external_env_never_overrides_local_env(tmp_path, monkeypatch) -> None:
    local = tmp_path / ".env"
    external = tmp_path / "external.env"
    local.write_text("VERTEXAI_PROJECT=local-project\n", encoding="utf-8")
    external.write_text(
        "VERTEXAI_PROJECT=external-project\nEXTERNAL_ONLY=available\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", local)
    monkeypatch.setenv("EXTERNAL_ENV_FILES", str(external))
    monkeypatch.delenv("VERTEXAI_PROJECT", raising=False)
    monkeypatch.delenv("EXTERNAL_ONLY", raising=False)
    config._bootstrap_external_env()
    assert "VERTEXAI_PROJECT" not in config.os.environ
    assert config.os.environ["EXTERNAL_ONLY"] == "available"
