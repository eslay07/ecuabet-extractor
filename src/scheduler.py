from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psutil


TASK_NAME = "Cuotas Ecuabet - viernes, sábado y domingo"


class RunLock:
    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                owner = json.loads(self.path.read_text(encoding="utf-8"))
                pid = int(owner["pid"])
                if psutil.pid_exists(pid):
                    raise RuntimeError(f"Ya existe una ejecución activa válida (PID {pid})")
            except (ValueError, KeyError, json.JSONDecodeError):
                raise RuntimeError("El archivo de bloqueo existe pero es inválido; requiere revisión")
            self.path.unlink()
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        descriptor = os.open(self.path, flags)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": datetime.now(ZoneInfo("America/Guayaquil")).isoformat()}, handle)
        self.acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.acquired and self.path.exists():
            try:
                owner = json.loads(self.path.read_text(encoding="utf-8"))
                if int(owner.get("pid", -1)) == os.getpid():
                    self.path.unlink()
            except Exception:
                pass


def create_windows_task(project_root: Path, python_executable: Path, test_marker: Path) -> None:
    if not test_marker.exists():
        raise RuntimeError("No se puede programar: la prueba técnica completa no ha sido validada")
    command = (
        "$ErrorActionPreference='Stop'; "
        f"$action=New-ScheduledTaskAction -Execute '{python_executable}' "
        f"-Argument '-m src.main run-scheduled' -WorkingDirectory '{project_root}'; "
        "$triggers=@(); "
        "$triggers+=New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Thursday -At 3:00PM; "
        "$triggers+=New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Friday -At 3:00PM; "
        "$triggers+=New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Saturday -At 3:00PM; "
        "$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 6) "
        "-MultipleInstances IgnoreNew -StartWhenAvailable; "
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $triggers "
        "-Settings $settings -Description 'Extracción local de cuotas prematch de Ecuabet' -Force | Out-Null"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], check=True, text=True, capture_output=True)


def next_scheduled_run(moment: datetime | None = None) -> datetime:
    now = moment or datetime.now(ZoneInfo("America/Guayaquil"))
    candidates: list[datetime] = []
    for delta in range(8):
        day = now.date() + timedelta(days=delta)
        if day.weekday() in {3, 4, 5}:
            candidate = datetime.combine(day, datetime.min.time().replace(hour=15), tzinfo=now.tzinfo)
            if candidate > now:
                candidates.append(candidate)
    return min(candidates)

