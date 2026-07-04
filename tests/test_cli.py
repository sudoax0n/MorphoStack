from __future__ import annotations

import json

from morphostack.cli.main import main


def test_default_command_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack local morphometry toolkit" in out


def test_doctor_prints_report(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack Doctor" in out
    assert "Dependencies:" in out


def test_doctor_json_is_valid(capsys):
    assert main(["doctor", "--json"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "platform" in payload
    assert "dependencies" in payload


def test_init_can_skip_dependency_install(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "MorphoStack first-run setup" in out
    assert "Skipped dependency installation" in out
