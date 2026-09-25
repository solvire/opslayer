"""Config .env write semantics: keys must be written as OPSLAYER_* names that
Config.load() reads back (the historical bug wrote attribute names instead)."""

from opslayer import config


def test_set_value_writes_env_name(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "_ENV_FILE", env_file)

    config.set_value("ops_host", "ops.example.com")

    text = env_file.read_text(encoding="utf-8")
    assert "OPSLAYER_OPS_HOST=ops.example.com" in text
    assert "ops_host=ops.example.com" not in text


def test_set_value_rejects_unknown_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / ".env")
    try:
        config.set_value("not_a_key", "x")
    except ValueError:
        return
    raise AssertionError("expected ValueError for an unknown key")


def test_set_value_preserves_every_other_line(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# my notes\n"
        "AWS_ACCESS_KEY_ID=AKIAEXAMPLE\n"
        "AWS_SECRET_ACCESS_KEY=shh/+=secret\n"
        "\n"
        "# section\n"
        "SOMETHING=keep me\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_ENV_FILE", env_file)

    config.set_value("ops_host", "ops.example.com")

    text = env_file.read_text(encoding="utf-8")
    assert "# my notes" in text
    assert "AWS_ACCESS_KEY_ID=AKIAEXAMPLE" in text
    assert "AWS_SECRET_ACCESS_KEY=shh/+=secret" in text
    assert "SOMETHING=keep me" in text
    assert "OPSLAYER_OPS_HOST=ops.example.com" in text


def test_set_value_replaces_existing_line_in_place(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nOPSLAYER_OPS_HOST=old\nB=2\n", encoding="utf-8")
    monkeypatch.setattr(config, "_ENV_FILE", env_file)

    config.set_value("ops_host", "new")

    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines == ["A=1", "OPSLAYER_OPS_HOST=new", "B=2"]


def test_unset_value_removes_env_name(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "_ENV_FILE", env_file)
    config.set_value("beszel_admin_email", "admin@example.com")

    config.unset_value("beszel_admin_email")

    assert "OPSLAYER_BESZEL_ADMIN_EMAIL" not in env_file.read_text(encoding="utf-8")
