from pathlib import Path

from src import validator


def test_pdftoppm_can_be_configured_explicitly(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "pdftoppm.exe"
    executable.write_bytes(b"test")
    monkeypatch.setenv("PDFTOPPM_PATH", str(executable))
    monkeypatch.setattr(validator.shutil, "which", lambda _name: None)
    assert validator._resolve_pdftoppm() == executable
