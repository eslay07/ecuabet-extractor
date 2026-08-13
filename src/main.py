from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import os
import platform
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .browser import LocalChrome, PublicAccessError
from .checkpoint import (
    atomic_write_json,
    backup_path,
    latest_backup_path,
    latest_manual_backup_path,
    manual_backup_path,
    manual_pdf_path,
    mirror_to_library,
    pdf_path,
    read_json,
)
from .discovery import NO_SCHEDULED_RUN, discover_board, event_key, now_guayaquil, production_target_day
from .extractor import extract_match, normalize_manual_market, timestamp
from .manual import MAX_MANUAL_MATCHES, parse_manual_matches
from .markets import EXTRACTION_ERROR, MARKETS, NOT_VERIFIABLE_ECUABET, VERIFIED, error_market
from .pdf_generator import build_pdf
from .referees import unavailable_referee
from .scheduler import RunLock, TASK_NAME, create_windows_task, next_scheduled_run
from .validator import ValidationFailure, render_pdf, validate_all, validate_json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.json"


def _manual_market_summary(data: dict[str, Any]) -> dict[str, int]:
    markets = [
        market
        for match in data.get("matches", [])
        for market in match.get("markets", [])
    ]
    return {
        "verified_markets": sum(market.get("status") == VERIFIED for market in markets),
        "extraction_errors": sum(
            market.get("status") == EXTRACTION_ERROR for market in markets
        ),
    }


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(ZoneInfo("America/Guayaquil")).isoformat(timespec="seconds"),
                "level": record.levelname,
                "event": record.getMessage(),
            },
            ensure_ascii=False,
        )


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def setup_logging(target_date: str) -> logging.Logger:
    path = PROJECT_ROOT / "logs" / f"Ecuabet_{target_date}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("EcuabetExtractor")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger


def make_backup(target_date: str, manifest: list[dict[str, Any]], started_at: str | None = None) -> dict[str, Any]:
    moment = now_guayaquil().isoformat(timespec="seconds")
    return {
        "schema_version": "1.0.0",
        "target_date": target_date,
        "timezone": "America/Guayaquil",
        "started_at": started_at or moment,
        "last_updated": moment,
        "overall_status": "DESCUBIERTO",
        "manifest": manifest,
        "discovered_count": len(manifest),
        "processed_count": 0,
        "pending_count": len(manifest),
        "matches": [],
        "errors": [],
        "validation": {"status": "PENDIENTE", "errors": []},
    }


def save_backup(data: dict[str, Any], config: dict[str, Any], logger: logging.Logger) -> tuple[Path, Path]:
    data["last_updated"] = now_guayaquil().isoformat(timespec="seconds")
    path = backup_path(PROJECT_ROOT, data["target_date"])
    atomic_write_json(path, data)
    logger.info(f"guardado_local:{path}")
    mirror = mirror_to_library(path, PROJECT_ROOT, config)
    logger.info(f"guardado_biblioteca:{mirror}")
    return path, mirror


def cmd_discover(args: argparse.Namespace) -> int:
    config = load_config()
    target = production_target_day()
    if target is None:
        logger = setup_logging(now_guayaquil().date().isoformat())
        logger.info(NO_SCHEDULED_RUN)
        print(NO_SCHEDULED_RUN)
        return 0
    logger = setup_logging(target.isoformat())
    logger.info(f"inicio:timezone=America/Guayaquil:target={target}")
    with LocalChrome(PROJECT_ROOT, config) as chrome:
        page = chrome.new_public_page(config["base_url"])
        manifest = discover_board(page, config, target, production=True)
    data = make_backup(target.isoformat(), manifest)
    save_backup(data, config, logger)
    logger.info(f"partidos_descubiertos:{len(manifest)}")
    print(f"Descubiertos: {len(manifest)}; fecha objetivo: {target}")
    return 0


def _latest_data() -> tuple[Path, dict[str, Any]]:
    path = latest_backup_path(PROJECT_ROOT)
    return path, read_json(path)


def cmd_extract_next(args: argparse.Namespace) -> int:
    config = load_config()
    path, data = _latest_data()
    logger = setup_logging(data["target_date"])
    processed_ids = {row.get("record_id") for row in data.get("matches", []) if row.get("status") == "PROCESADO"}
    pending = next((row for row in data["manifest"] if row.get("record_id") not in processed_ids), None)
    if pending is None:
        print("No hay partidos pendientes.")
        return 0

    def checkpoint(match: dict[str, Any]) -> None:
        by_id = {row.get("record_id"): row for row in data.get("matches", [])}
        by_id[match["record_id"]] = match
        data["matches"] = [by_id[row["record_id"]] for row in data["manifest"] if row["record_id"] in by_id]
        data["processed_count"] = sum(row.get("status") == "PROCESADO" for row in data["matches"])
        data["pending_count"] = data["discovered_count"] - data["processed_count"]
        save_backup(data, config, logger)

    logger.info(f"partido_actual:{pending['home']} vs {pending['away']}")
    with LocalChrome(PROJECT_ROOT, config) as chrome:
        page = chrome.new_public_page(pending["url"])
        extract_match(page, pending, config["market_stability_timeout_ms"], checkpoint)
    print(f"Procesado: {pending['home']} vs {pending['away']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path, data = _latest_data()
    print(json.dumps({
        "json": str(path),
        "fecha_objetivo": data["target_date"],
        "estado": data["overall_status"],
        "descubiertos": data["discovered_count"],
        "procesados": data["processed_count"],
        "pendientes": data["pending_count"],
        "validacion": data.get("validation"),
    }, ensure_ascii=False, indent=2))
    return 0


def _save_manual_backup(
    data: dict[str, Any], config: dict[str, Any], logger: logging.Logger
) -> tuple[Path, Path]:
    data["last_updated"] = now_guayaquil().isoformat(timespec="seconds")
    path = manual_backup_path(PROJECT_ROOT, data["target_date"])
    atomic_write_json(path, data)
    logger.info(f"guardado_manual_local:{path}")
    mirror = mirror_to_library(path, PROJECT_ROOT, config)
    logger.info(f"guardado_manual_biblioteca:{mirror}")
    return path, mirror


def cmd_manual_status(args: argparse.Namespace) -> int:
    path = latest_manual_backup_path(PROJECT_ROOT)
    data = read_json(path)
    print(
        json.dumps(
            {
                "json": str(path),
                "pdf": str(manual_pdf_path(PROJECT_ROOT, data["target_date"])),
                "fecha_objetivo": data["target_date"],
                "estado": data["overall_status"],
                "partidos": data["discovered_count"],
                "procesados": data["processed_count"],
                "pendientes": data["pending_count"],
                "validacion": data.get("validation"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_manual_validate(args: argparse.Namespace) -> int:
    """Finish an interrupted manual run without consulting Ecuabet again."""
    config = load_config()
    json_file = latest_manual_backup_path(PROJECT_ROOT)
    data = read_json(json_file)
    coverage_errors = validate_json(data)
    if coverage_errors:
        raise ValidationFailure("; ".join(coverage_errors))
    destination = manual_pdf_path(PROJECT_ROOT, data["target_date"])
    if not destination.exists():
        raise FileNotFoundError(f"No existe el PDF manual: {destination}")
    result = validate_all(json_file, destination)
    summary = _manual_market_summary(data)
    data["validation"] = result
    data["overall_status"] = (
        "SELECCIÓN_MANUAL_VALIDADA_CON_ERRORES"
        if summary["extraction_errors"]
        else "SELECCIÓN_MANUAL_VALIDADA"
    )
    data["last_updated"] = now_guayaquil().isoformat(timespec="seconds")
    atomic_write_json(json_file, data)
    json_mirror = mirror_to_library(json_file, PROJECT_ROOT, config)
    pdf_mirror = mirror_to_library(destination, PROJECT_ROOT, config)
    logger = setup_logging(f"Manual_{data['target_date']}")
    logger.info(f"recuperacion_manual:{json.dumps(result, ensure_ascii=False)}")
    payload = {
        "status": "VALIDADO",
        "matches": data["processed_count"],
        "json": str(json_file),
        "json_mirror": str(json_mirror),
        "pdf": str(destination),
        "pdf_mirror": str(pdf_mirror),
        "validation": result,
        **summary,
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    return 0


def cmd_manual_run(args: argparse.Namespace) -> int:
    config = load_config()
    try:
        target = date.fromisoformat(args.date)
    except ValueError as error:
        raise ValueError("La fecha debe tener formato AAAA-MM-DD") from error
    input_path = Path(args.matches_file).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"No existe la lista de partidos: {input_path}")
    manifest = parse_manual_matches(
        input_path.read_text(encoding="utf-8").splitlines(),
        target,
        config["base_url"],
    )
    logger = setup_logging(f"Manual_{target.isoformat()}")
    logger.info(f"inicio_manual:target={target}:partidos={len(manifest)}")

    with RunLock(PROJECT_ROOT / "work" / "ecuabet.lock"):
        destination = manual_pdf_path(PROJECT_ROOT, target.isoformat())
        if destination.exists():
            history = destination.parent / "previous"
            history.mkdir(parents=True, exist_ok=True)
            archived = history / (
                f"{destination.stem}_{now_guayaquil().strftime('%Y%m%d_%H%M%S')}"
                f"{destination.suffix}"
            )
            os.replace(destination, archived)
            logger.info(f"pdf_manual_anterior_archivado:{archived}")
        data = make_backup(target.isoformat(), manifest)
        data.update(
            {
                "overall_status": "SELECCIÓN_MANUAL_PENDIENTE",
                "execution_mode": "MANUAL",
                "production_league_filter": False,
                "manual_limit": MAX_MANUAL_MATCHES,
            }
        )
        json_file, _ = _save_manual_backup(data, config, logger)

        def checkpoint(match: dict[str, Any]) -> None:
            by_id = {row.get("record_id"): row for row in data.get("matches", [])}
            by_id[match["record_id"]] = match
            data["matches"] = [
                by_id[row["record_id"]]
                for row in data["manifest"]
                if row["record_id"] in by_id
            ]
            data["processed_count"] = sum(
                row.get("status") == "PROCESADO" for row in data["matches"]
            )
            data["pending_count"] = data["discovered_count"] - data["processed_count"]
            data["overall_status"] = (
                "SELECCIÓN_MANUAL_PROCESADA"
                if data["pending_count"] == 0
                else "SELECCIÓN_MANUAL_EN_PROGRESO"
            )
            _save_manual_backup(data, config, logger)

        try:
            with LocalChrome(PROJECT_ROOT, config) as chrome:
                page = chrome.new_public_page(config["base_url"])
                for index, match in enumerate(manifest, start=1):
                    print(
                        f"[{index}/{len(manifest)}] {match['home']} vs {match['away']}",
                        flush=True,
                    )
                    logger.info(
                        f"partido_manual:{index}/{len(manifest)}:{match['home']} vs {match['away']}"
                    )
                    try:
                        extract_match(
                            page,
                            match,
                            config["market_stability_timeout_ms"],
                            checkpoint,
                        )
                    except PublicAccessError:
                        raise
                    except Exception as error:
                        queried_at = timestamp()
                        message = f"{NOT_VERIFIABLE_ECUABET} {type(error).__name__}: {error}"
                        failed = dict(match)
                        failed.update(
                            {
                                "status": "PROCESADO",
                                "verification_status": NOT_VERIFIABLE_ECUABET,
                                "queried_at": queried_at,
                                "last_updated": queried_at,
                                "markets": [
                                    error_market(spec, queried_at, message) for spec in MARKETS
                                ],
                                "referee": unavailable_referee(queried_at),
                                "reloads": 0,
                                "errors": [message],
                            }
                        )
                        logger.error(message)
                        print(message, flush=True)
                        checkpoint(failed)
        except PublicAccessError as error:
            message = f"DETENIDO: {error}"
            data["overall_status"] = "DETENIDA_POR_ACCESO"
            data["validation"] = {"status": "ERROR", "errors": [message]}
            if message not in data["errors"]:
                data["errors"].append(message)
            logger.error(message)
            print(message, flush=True)
            _save_manual_backup(data, config, logger)
            raise

        preflight_errors = validate_json(data)
        if preflight_errors:
            data["overall_status"] = "DETENIDA_SIN_CUOTAS_VERIFICADAS"
            data["validation"] = {"status": "ERROR", "errors": preflight_errors}
            data["errors"].extend(preflight_errors)
            _save_manual_backup(data, config, logger)
            raise ValidationFailure(
                "No se generó el PDF porque no contiene cuotas verificadas: "
                + "; ".join(preflight_errors)
            )
        build_pdf(data, destination)
        result = validate_all(json_file, destination)
        summary = _manual_market_summary(data)
        data["validation"] = result
        data["overall_status"] = (
            "SELECCIÓN_MANUAL_VALIDADA_CON_ERRORES"
            if summary["extraction_errors"]
            else "SELECCIÓN_MANUAL_VALIDADA"
        )
        data["last_updated"] = now_guayaquil().isoformat(timespec="seconds")
        atomic_write_json(json_file, data)
        mirror_to_library(json_file, PROJECT_ROOT, config)
        pdf_mirror = mirror_to_library(destination, PROJECT_ROOT, config)
        logger.info(f"fin_manual:{json.dumps(result, ensure_ascii=False)}")
        print(
            json.dumps(
                {
                    "status": "VALIDADO",
                    "matches": len(manifest),
                    "json": str(json_file),
                    "pdf": str(destination),
                    "pdf_mirror": str(pdf_mirror),
                    "validation": result,
                    **summary,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return 0


def cmd_build_pdf(args: argparse.Namespace) -> int:
    path, data = _latest_data()
    destination = pdf_path(PROJECT_ROOT, data["target_date"])
    build_pdf(data, destination)
    print(destination)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config = load_config()
    json_file, data = _latest_data()
    destination = pdf_path(PROJECT_ROOT, data["target_date"])
    result = validate_all(json_file, destination)
    data["validation"] = result
    data["overall_status"] = "VALIDADO"
    data["last_updated"] = now_guayaquil().isoformat(timespec="seconds")
    logger = setup_logging(data["target_date"])
    atomic_write_json(json_file, data)
    mirror_to_library(json_file, PROJECT_ROOT, config)
    mirror = mirror_to_library(destination, PROJECT_ROOT, config)
    logger.info(f"validacion:{json.dumps(result, ensure_ascii=False)}")
    logger.info(f"guardado_biblioteca_pdf:{mirror}")
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _manual_backup(config: dict[str, Any], count: int, after: str) -> dict[str, Any]:
    source = PROJECT_ROOT / config["manual_observation_path"]
    observed = json.loads(source.read_text(encoding="utf-8"))
    if len(observed) < count:
        raise RuntimeError(f"La observación manual solo contiene {len(observed)} partidos")
    selected = [row for row in observed if row["time"] >= after][:count]
    if len(selected) != count:
        raise RuntimeError(f"No hay {count} partidos observados desde las {after}")
    manifest: list[dict[str, Any]] = []
    processed: list[dict[str, Any]] = []
    for raw in selected:
        observed_at = raw["queried_at"]
        parsed_at = datetime.fromisoformat(observed_at)
        if parsed_at.tzinfo is None:
            observed_at = parsed_at.replace(tzinfo=ZoneInfo("America/Guayaquil")).isoformat(timespec="seconds")
        record_id = event_key(raw["league"], raw["date"], raw["home"], raw["away"], raw.get("internal_id"))
        manifest_row = {
            "record_id": record_id,
            "league": raw["league"],
            "date": raw["date"],
            "time": raw["time"],
            "home": raw["home"],
            "away": raw["away"],
            "url": raw["url"],
            "internal_id": raw.get("internal_id"),
            "status": "PROCESADO",
        }
        manifest.append(manifest_row)
        match = dict(manifest_row)
        match.update(
            {
                "queried_at": observed_at,
                "last_updated": observed_at,
                "status": "PROCESADO",
                "markets": [normalize_manual_market(market) for market in raw["markets"]],
                "referee": unavailable_referee(observed_at),
                "reloads": 0,
                "errors": [],
            }
        )
        for market in match["markets"]:
            market["queried_at"] = market.get("queried_at") or observed_at
        processed.append(match)
    first_started_at = datetime.fromisoformat(selected[0]["queried_at"])
    if first_started_at.tzinfo is None:
        first_started_at = first_started_at.replace(tzinfo=ZoneInfo("America/Guayaquil"))
    data = make_backup(selected[0]["date"], manifest, first_started_at.isoformat(timespec="seconds"))
    data.update(
        {
            "overall_status": "PRUEBA_TECNICA_PROCESADA",
            "processed_count": count,
            "pending_count": 0,
            "matches": processed,
            "test_parameters": {"matches": count, "after": after, "production_league_filter": False},
        }
    )
    return data


def cmd_test(args: argparse.Namespace) -> int:
    config = load_config()
    data = _manual_backup(config, args.matches, args.after)
    logger = setup_logging(data["target_date"])
    logger.info(f"inicio_prueba:matches={args.matches}:after={args.after}")
    json_file, _ = save_backup(data, config, logger)
    destination = pdf_path(PROJECT_ROOT, data["target_date"])
    build_pdf(data, destination)
    result = validate_all(json_file, destination)
    data["validation"] = result
    data["overall_status"] = "PRUEBA_TECNICA_VALIDADA"
    data["last_updated"] = now_guayaquil().isoformat(timespec="seconds")
    atomic_write_json(json_file, data)
    mirror_to_library(json_file, PROJECT_ROOT, config)
    mirror_to_library(destination, PROJECT_ROOT, config)
    marker = PROJECT_ROOT / "work" / "manual_test_passed.json"
    atomic_write_json(marker, {
        "status": "PASÓ",
        "validated_at": data["last_updated"],
        "matches": args.matches,
        "after": args.after,
        "json": str(json_file),
        "pdf": str(destination),
        "validation": result,
    })
    logger.info(f"fin_prueba:{json.dumps(result, ensure_ascii=False)}")
    print(json.dumps({"status": "PASÓ", "json": str(json_file), "pdf": str(destination), **result}, ensure_ascii=False))
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    python_executable = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    create_windows_task(PROJECT_ROOT, python_executable, PROJECT_ROOT / "work" / "manual_test_passed.json")
    print(json.dumps({"task": TASK_NAME, "next_run": next_scheduled_run().isoformat()}, ensure_ascii=False))
    return 0


def cmd_run_scheduled(args: argparse.Namespace) -> int:
    if production_target_day() is None:
        logger = setup_logging(now_guayaquil().date().isoformat())
        logger.info(NO_SCHEDULED_RUN)
        print(NO_SCHEDULED_RUN)
        return 0
    with RunLock(PROJECT_ROOT / "work" / "ecuabet.lock"):
        cmd_discover(args)
        while True:
            _, data = _latest_data()
            if data["pending_count"] <= 0:
                break
            cmd_extract_next(args)
        cmd_build_pdf(args)
        cmd_validate(args)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="EcuabetExtractor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover").set_defaults(func=cmd_discover)
    sub.add_parser("extract-next").set_defaults(func=cmd_extract_next)
    sub.add_parser("status").set_defaults(func=cmd_status)
    manual = sub.add_parser("manual-run")
    manual.add_argument("--date", required=True, help="Fecha objetivo AAAA-MM-DD")
    manual.add_argument("--matches-file", required=True, help="Archivo UTF-8, un partido por línea")
    manual.set_defaults(func=cmd_manual_run)
    sub.add_parser("manual-status").set_defaults(func=cmd_manual_status)
    sub.add_parser("manual-validate").set_defaults(func=cmd_manual_validate)
    sub.add_parser("build-pdf").set_defaults(func=cmd_build_pdf)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    test = sub.add_parser("test")
    test.add_argument("--matches", type=int, default=5)
    test.add_argument("--after", default="13:00")
    test.set_defaults(func=cmd_test)
    sub.add_parser("schedule").set_defaults(func=cmd_schedule)
    sub.add_parser("run-scheduled").set_defaults(func=cmd_run_scheduled)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrumpido por el usuario", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
