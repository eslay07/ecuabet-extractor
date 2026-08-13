from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pdfplumber
from PIL import Image, ImageChops
from pypdf import PdfReader

from .markets import MARKETS, UNAVAILABLE_MESSAGE


class ValidationFailure(RuntimeError):
    pass


def _iter_xobjects(resources: Any) -> Iterable[Any]:
    if not resources or "/XObject" not in resources:
        return []
    objects = resources["/XObject"].get_object()
    return [value.get_object() for value in objects.values()]


def count_pdf_images(reader: PdfReader) -> int:
    count = 0
    for page in reader.pages:
        resources = page.get("/Resources")
        for obj in _iter_xobjects(resources):
            if obj.get("/Subtype") == "/Image":
                count += 1
    return count


def validate_json(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    manifest = data.get("manifest", [])
    matches = data.get("matches", [])
    if data.get("discovered_count") != len(manifest):
        errors.append("El total descubierto no coincide con el manifiesto")
    if len(matches) != data.get("processed_count"):
        errors.append("El total procesado no coincide con los partidos persistidos")
    manifest_ids = {row.get("record_id") for row in manifest}
    match_ids = {row.get("record_id") for row in matches}
    if not match_ids.issubset(manifest_ids):
        errors.append("Hay partidos procesados que no pertenecen al manifiesto")
    for match in matches:
        markets = match.get("markets", [])
        if len(markets) != len(MARKETS):
            errors.append(f"{match.get('home')} vs {match.get('away')}: no contiene 12 mercados")
            continue
        for expected, market in zip(MARKETS, sorted(markets, key=lambda row: int(row["id"]))):
            if int(market.get("id", -1)) != expected["id"]:
                errors.append(f"Orden o id incorrecto en {expected['name']}")
            status = market.get("status")
            if status not in {"VERIFICADO", "NO DISPONIBLE EN ECUABET", "ERROR DE EXTRACCIÓN"}:
                errors.append(f"Estado inválido: {status}")
            if status == "NO DISPONIBLE EN ECUABET" and market.get("message") != UNAVAILABLE_MESSAGE:
                errors.append(f"Texto de no disponibilidad incorrecto: {market.get('name')}")
            if status == "VERIFICADO":
                if not market.get("data"):
                    errors.append(f"Mercado verificado sin datos: {market.get('name')}")
                for row in market.get("data", []):
                    if not isinstance(row.get("odd"), str) or not row.get("odd"):
                        errors.append(f"Cuota no conservada como texto: {market.get('name')}")
            slider = market.get("slider")
            if slider:
                step = int(slider["step"])
                expected_positions = list(range(int(slider["min"]), int(slider["max"]) + 1, step))
                if slider.get("visited_positions") != expected_positions or slider.get("complete") is not True:
                    errors.append(f"Deslizador incompleto: {market.get('name')}")
        if data.get("execution_mode") == "MANUAL" and not any(
            market.get("status") == "VERIFICADO" for market in markets
        ):
            errors.append(
                f"{match.get('home')} vs {match.get('away')}: "
                "ningún mercado contiene cuotas verificadas"
            )
    return errors


def validate_pdf(data: dict[str, Any], pdf_path: Path) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    reader = PdfReader(str(pdf_path))
    images = count_pdf_images(reader)
    if images:
        errors.append(f"El PDF contiene {images} objetos de imagen")
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
    full_text = "\n".join(page_texts)
    if not full_text.strip():
        errors.append("El PDF no tiene texto extraíble")
    for match in data.get("matches", []):
        if match["home"] not in full_text or match["away"] not in full_text:
            errors.append(f"Partido ausente del PDF: {match['home']} vs {match['away']}")
        for market in match.get("markets", []):
            if market["name"] not in full_text:
                errors.append(f"Mercado ausente del PDF: {market['name']}")
            for row in market.get("data", []):
                odd = row.get("odd")
                if odd and str(odd) not in full_text:
                    errors.append(f"Cuota ausente del PDF: {odd}")
    return errors, {"pages": len(reader.pages), "images": images, "text_characters": len(full_text)}


def _resolve_pdftoppm() -> Path:
    configured = os.environ.get("PDFTOPPM_PATH")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate

    command = shutil.which("pdftoppm")
    if command:
        candidate = Path(command)
        if candidate.suffix.casefold() in {".cmd", ".bat"}:
            bundled = (
                candidate.parents[2]
                / "native"
                / "poppler"
                / "Library"
                / "bin"
                / "pdftoppm.exe"
            )
            if bundled.is_file():
                return bundled
        return candidate

    project_copy = Path(__file__).resolve().parents[1] / "tools" / "poppler" / "bin" / "pdftoppm.exe"
    if project_copy.is_file():
        return project_copy

    runtime_root = Path.home() / ".cache" / "codex-runtimes"
    if runtime_root.is_dir():
        runtime_copies = sorted(
            runtime_root.glob(
                "*/dependencies/native/poppler/Library/bin/pdftoppm.exe"
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if runtime_copies:
            return runtime_copies[0]

    raise FileNotFoundError(
        "pdftoppm no está disponible para el control visual. "
        "Defina PDFTOPPM_PATH o instale Poppler."
    )


def render_pdf(pdf_path: Path, output_dir: Path | None = None) -> list[Path]:
    output_dir = output_dir or Path(tempfile.mkdtemp(prefix="ecuabet_pdf_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    command = _resolve_pdftoppm()
    prefix = output_dir / "page"
    arguments = [str(command), "-png", "-r", "110", str(pdf_path), str(prefix)]
    if command.suffix.casefold() in {".cmd", ".bat"}:
        arguments = ["cmd.exe", "/d", "/c", *arguments]
    subprocess.run(arguments, check=True, capture_output=True, text=True)
    return sorted(output_dir.glob("page-*.png"))


def validate_rendered_pages(pages: list[Path]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    ink_ratios: list[float] = []
    for page_number, path in enumerate(pages, start=1):
        with Image.open(path) as source:
            gray = source.convert("L")
            white = Image.new("L", gray.size, 255)
            difference = ImageChops.difference(gray, white)
            ink = sum(1 for pixel in difference.getdata() if pixel > 12)
            ratio = ink / (gray.width * gray.height)
            ink_ratios.append(ratio)
            if ratio < 0.001:
                errors.append(f"Página visualmente vacía: {page_number}")
            bbox = difference.getbbox()
            if bbox and (bbox[0] <= 1 or bbox[1] <= 1 or bbox[2] >= gray.width - 1 or bbox[3] >= gray.height - 1):
                errors.append(f"Contenido tocando el borde físico en página {page_number}")
    return errors, {
        "rendered_pages": len(pages),
        "minimum_ink_ratio": min(ink_ratios) if ink_ratios else 0,
    }


def validate_all(json_path: Path, pdf_path: Path) -> dict[str, Any]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    json_errors = validate_json(data)
    pdf_errors, details = validate_pdf(data, pdf_path)
    temporary = Path(tempfile.mkdtemp(prefix="ecuabet_visual_"))
    try:
        rendered = render_pdf(pdf_path, temporary)
        render_errors, render_details = validate_rendered_pages(rendered)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    errors = json_errors + pdf_errors + render_errors
    if errors:
        raise ValidationFailure("; ".join(errors))
    return {"status": "VALIDADO", "errors": [], **details, **render_details}
