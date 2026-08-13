from src.checkpoint import atomic_write_json, read_json


def test_atomic_json_round_trip(tmp_path) -> None:
    destination = tmp_path / "respaldo.json"
    value = {"cuota": "1.90", "texto": "Sí"}
    atomic_write_json(destination, value)
    assert read_json(destination) == value
    assert not list(tmp_path.glob("*.tmp"))

