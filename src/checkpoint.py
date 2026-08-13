from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"El JSON raíz debe ser un objeto: {path}")
    return data


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        read_json(tmp_path)
        os.replace(tmp_path, path)
        persisted = read_json(path)
        if persisted != data:
            raise IOError(f"La verificación posterior al reemplazo falló: {path}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copy2(source, tmp_path)
        if tmp_path.stat().st_size != source.stat().st_size:
            raise IOError("El tamaño del archivo temporal no coincide con el origen")
        os.replace(tmp_path, destination)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def mirror_to_library(source: Path, project_root: Path, config: dict[str, Any]) -> Path:
    mirror_dir = project_root / config["library_mirror_dir"]
    destination = mirror_dir / source.name
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            atomic_copy(source, destination)
            if source.suffix.lower() == ".json":
                read_json(destination)
            if destination.stat().st_size <= 0:
                raise IOError("El archivo reflejado quedó vacío")
            return destination
        except Exception as exc:  # exactamente un reintento
            last_error = exc
            if attempt == 0:
                time.sleep(0.25)
    raise IOError(f"Dos fallos consecutivos al guardar en la Biblioteca: {last_error}")


def backup_path(project_root: Path, target_date: str) -> Path:
    return project_root / "output" / target_date / f"Respaldo_Cuotas_Ecuabet_{target_date}.json"


def pdf_path(project_root: Path, target_date: str) -> Path:
    return project_root / "output" / target_date / f"Cuotas_Ecuabet_{target_date}.pdf"


def manual_backup_path(project_root: Path, target_date: str) -> Path:
    return (
        project_root
        / "output"
        / target_date
        / f"Respaldo_Cuotas_Ecuabet_Manual_{target_date}.json"
    )


def manual_pdf_path(project_root: Path, target_date: str) -> Path:
    return project_root / "output" / target_date / f"Cuotas_Ecuabet_Manual_{target_date}.pdf"


def latest_manual_backup_path(project_root: Path) -> Path:
    candidates = sorted(
        (project_root / "output").glob("*/Respaldo_Cuotas_Ecuabet_Manual_*.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError("No existe una ejecución manual en output/")
    return candidates[-1]


def latest_backup_path(project_root: Path) -> Path:
    candidates = sorted((project_root / "output").glob("*/Respaldo_Cuotas_Ecuabet_*.json"))
    if not candidates:
        raise FileNotFoundError("No existe un respaldo JSON en output/")
    return candidates[-1]
