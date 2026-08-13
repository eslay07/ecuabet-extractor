from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk

from .checkpoint import latest_manual_backup_path, manual_pdf_path, read_json
from .discovery import now_guayaquil
from .main import PROJECT_ROOT, load_config
from .manual import MAX_MANUAL_MATCHES, ManualInputError, parse_manual_matches


class EcuabetApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("EcuabetExtractor — Ejecución manual")
        self.geometry("920x760")
        self.minsize(780, 650)
        self.configure(bg="#F3F6F8")
        self.protocol("WM_DELETE_WINDOW", self._close_window)

        self.config_data = load_config()
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.last_pdf: Path | None = None
        self.date_value = tk.StringVar(value=now_guayaquil().date().isoformat())
        self.counter_value = tk.StringVar(value=f"0 / {MAX_MANUAL_MATCHES} partidos")
        self.status_value = tk.StringVar(value="Listo para configurar una ejecución manual")
        self._configure_styles()
        self._build_layout()
        self.after(120, self._drain_messages)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Title.TLabel", background="#F3F6F8", foreground="#14213D", font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background="#F3F6F8", foreground="#52606D", font=("Segoe UI", 10))
        style.configure("Card.TFrame", background="#FFFFFF", relief="flat")
        style.configure("Card.TLabel", background="#FFFFFF", foreground="#243B53", font=("Segoe UI", 10))
        style.configure("Field.TLabel", background="#FFFFFF", foreground="#102A43", font=("Segoe UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(16, 10), foreground="#FFFFFF", background="#0B6E4F")
        style.map("Primary.TButton", background=[("active", "#095C43"), ("disabled", "#9FB3C8")])
        style.configure("Secondary.TButton", font=("Segoe UI", 9), padding=(12, 8))
        style.configure("Status.TLabel", background="#E8F5EF", foreground="#0B6E4F", padding=8, font=("Segoe UI", 9, "bold"))

    def _build_layout(self) -> None:
        outer = ttk.Frame(self, padding=(28, 22), style="Card.TFrame")
        outer.pack(fill="both", expand=True, padx=22, pady=18)

        ttk.Label(outer, text="EcuabetExtractor", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Seleccione cualquier fecha y escriba hasta 50 partidos. La programación automática no se modifica.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 18))

        form = ttk.Frame(outer, style="Card.TFrame")
        form.pack(fill="both", expand=True)
        top = ttk.Frame(form, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Fecha de los partidos", style="Field.TLabel").pack(side="left")
        date_entry = ttk.Entry(top, textvariable=self.date_value, width=14, font=("Segoe UI", 10))
        date_entry.pack(side="left", padx=(12, 12))
        ttk.Label(top, text="Formato: AAAA-MM-DD · Se permite cualquier día", style="Card.TLabel").pack(side="left")

        list_header = ttk.Frame(form, style="Card.TFrame")
        list_header.pack(fill="x", pady=(18, 6))
        ttk.Label(list_header, text="Partidos — uno por línea", style="Field.TLabel").pack(side="left")
        ttk.Label(list_header, textvariable=self.counter_value, style="Card.TLabel").pack(side="right")

        text_frame = ttk.Frame(form, style="Card.TFrame")
        text_frame.pack(fill="both", expand=True)
        self.matches_text = tk.Text(
            text_frame,
            height=14,
            wrap="word",
            undo=True,
            font=("Consolas", 10),
            bg="#FBFCFE",
            fg="#102A43",
            insertbackground="#102A43",
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=9,
        )
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.matches_text.yview)
        self.matches_text.configure(yscrollcommand=scrollbar.set)
        self.matches_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.matches_text.bind("<KeyRelease>", lambda _event: self._update_counter())

        ttk.Label(
            form,
            text=(
                "Ejemplos:  Real Madrid vs Barcelona    ·    20:00 | Inter de Milán vs Venezia    ·    "
                "LaLiga | 20:00 | Real Madrid vs Barcelona"
            ),
            style="Card.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(7, 2))
        ttk.Label(
            form,
            text="Solo se extraerán partidos que estén publicados en la cartelera pública de Ecuabet para la fecha indicada.",
            style="Card.TLabel",
            wraplength=820,
        ).pack(anchor="w", pady=(0, 12))

        actions = ttk.Frame(form, style="Card.TFrame")
        actions.pack(fill="x")
        self.run_button = ttk.Button(actions, text="▶ Ejecutar ahora", style="Primary.TButton", command=self._start_run)
        self.run_button.pack(side="left")
        self.validate_button = ttk.Button(actions, text="Validar lista", style="Secondary.TButton", command=self._validate_and_report)
        self.validate_button.pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="Limpiar", style="Secondary.TButton", command=self._clear).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Abrir resultados", style="Secondary.TButton", command=self._open_results).pack(side="right")
        self.pdf_button = ttk.Button(actions, text="Abrir último PDF", style="Secondary.TButton", command=self._open_pdf)
        self.pdf_button.pack(side="right", padx=(0, 8))

        self.progress = ttk.Progressbar(form, mode="indeterminate")
        self.progress.pack(fill="x", pady=(14, 8))
        ttk.Label(form, textvariable=self.status_value, style="Status.TLabel").pack(fill="x")

        log_frame = ttk.LabelFrame(form, text="Actividad", padding=6)
        log_frame.pack(fill="both", expand=False, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=7, wrap="word", state="disabled", font=("Consolas", 9), bg="#101F2E", fg="#D9E2EC", padx=8, pady=6)
        self.log_text.pack(fill="both", expand=True)

    def _raw_lines(self) -> list[str]:
        return self.matches_text.get("1.0", "end").splitlines()

    def _validated_manifest(self) -> list[dict[str, object]]:
        try:
            target = date.fromisoformat(self.date_value.get().strip())
        except ValueError as error:
            raise ManualInputError("La fecha debe tener formato AAAA-MM-DD.") from error
        return parse_manual_matches(self._raw_lines(), target, self.config_data["sport_route"])

    def _update_counter(self) -> None:
        count = sum(1 for line in self._raw_lines() if line.strip())
        self.counter_value.set(f"{count} / {MAX_MANUAL_MATCHES} partidos")

    def _validate_and_report(self) -> None:
        try:
            manifest = self._validated_manifest()
        except ManualInputError as error:
            messagebox.showerror("Revise la lista", str(error), parent=self)
            return
        self.status_value.set(f"Lista válida: {len(manifest)} partidos para {self.date_value.get().strip()}")
        messagebox.showinfo("Lista válida", f"Se procesarán {len(manifest)} partidos.", parent=self)

    def _start_run(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Ejecución activa", "Ya existe una ejecución manual en curso.", parent=self)
            return
        try:
            manifest = self._validated_manifest()
        except ManualInputError as error:
            messagebox.showerror("Revise la lista", str(error), parent=self)
            return
        if not messagebox.askyesno(
            "Confirmar ejecución",
            f"Se consultarán {len(manifest)} partidos del {self.date_value.get().strip()}.\n\n"
            "Una lista grande puede tardar varias horas. ¿Desea continuar?",
            parent=self,
        ):
            return

        input_path = PROJECT_ROOT / "work" / "gui_manual_matches.txt"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = input_path.with_suffix(".tmp")
        temporary.write_text("\n".join(row["manual_input"] for row in manifest) + "\n", encoding="utf-8")
        os.replace(temporary, input_path)
        python = Path(sys.executable)
        if python.name.casefold() == "pythonw.exe":
            python = python.with_name("python.exe")
        command = [
            str(python),
            "-m",
            "src.main",
            "manual-run",
            "--date",
            self.date_value.get().strip(),
            "--matches-file",
            str(input_path),
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        self.run_button.configure(state="disabled")
        self.validate_button.configure(state="disabled")
        self.progress.start(10)
        self.status_value.set(f"Procesando {len(manifest)} partidos… no cierre esta ventana")
        self._append_log("Ejecución iniciada. Chrome local se abrirá automáticamente.\n")
        threading.Thread(target=self._read_process, daemon=True).start()

    def _read_process(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        final_payload: dict[str, object] | None = None
        output_tail: list[str] = []
        for line in self.process.stdout:
            self.messages.put(("log", line))
            output_tail.append(line.rstrip())
            output_tail = output_tail[-20:]
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    final_payload = parsed
            except json.JSONDecodeError:
                pass
        code = self.process.wait()
        self.messages.put(("done", (code, final_payload, "\n".join(output_tail))))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "done":
                    code, result, details = payload  # type: ignore[misc]
                    self._finish_run(int(code), result, str(details))
        except queue.Empty:
            pass
        self.after(120, self._drain_messages)

    def _finish_run(self, code: int, result: object, details: str = "") -> None:
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.validate_button.configure(state="normal")
        if code == 0 and isinstance(result, dict):
            pdf = result.get("pdf_mirror") or result.get("pdf")
            self.last_pdf = Path(str(pdf)) if pdf else None
            extraction_errors = int(result.get("extraction_errors", 0) or 0)
            verified_markets = int(result.get("verified_markets", 0) or 0)
            if extraction_errors:
                self.status_value.set(
                    f"Finalizado con datos parciales: {verified_markets} mercados verificados · "
                    f"{extraction_errors} errores"
                )
                messagebox.showwarning(
                    "Resultado parcial",
                    "El JSON y el PDF fueron guardados y validados, pero Ecuabet no "
                    f"expuso todos los mercados. Verificados: {verified_markets}. "
                    f"Errores de extracción: {extraction_errors}.",
                    parent=self,
                )
            else:
                self.status_value.set(
                    f"Finalizado: {result.get('matches', 0)} partidos · PDF validado"
                )
                messagebox.showinfo(
                    "Ejecución terminada",
                    "El JSON y el PDF fueron guardados y validados.",
                    parent=self,
                )
        else:
            self.status_value.set("La ejecución terminó con un error. Revise el panel de actividad.")
            detail_lines = [line for line in details.splitlines() if line.strip()]
            detail = (
                "\n".join(detail_lines[-4:])
                if detail_lines
                else f"Código de salida: {code}"
            )
            messagebox.showerror(
                "Error de ejecución",
                f"No se pudo completar la ejecución manual.\n\nDetalle:\n{detail[:1200]}",
                parent=self,
            )

    def _append_log(self, value: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", value)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.matches_text.delete("1.0", "end")
        self._update_counter()
        self.status_value.set("Lista limpia")

    def _open_results(self) -> None:
        target = self.date_value.get().strip()
        folder = PROJECT_ROOT / "output" / target
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # type: ignore[attr-defined]

    def _open_pdf(self) -> None:
        candidate = self.last_pdf
        if candidate is None:
            try:
                data = read_json(latest_manual_backup_path(PROJECT_ROOT))
                candidate = manual_pdf_path(PROJECT_ROOT, data["target_date"])
            except Exception:
                candidate = None
        if not candidate or not candidate.exists():
            messagebox.showwarning("PDF no disponible", "Todavía no existe un PDF manual validado.", parent=self)
            return
        os.startfile(candidate)  # type: ignore[attr-defined]

    def _close_window(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning(
                "Ejecución activa",
                "Espere a que termine la ejecución antes de cerrar la aplicación.",
                parent=self,
            )
            return
        self.destroy()


def main() -> None:
    app = EcuabetApp()
    app.mainloop()


if __name__ == "__main__":
    main()
