from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterator

import psutil
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


BLOCK_PATTERNS = {
    "Cloudflare Error 1009": re.compile(r"error\s*1009", re.I),
    "Access denied": re.compile(r"access\s+denied|acceso\s+denegado", re.I),
    "Bloqueo regional": re.compile(
        r"not available in your (?:country|region)|country or region has been banned|bloqueo regional",
        re.I,
    ),
    "CAPTCHA": re.compile(r"captcha|verify you are human|verifica que eres humano", re.I),
}


class PublicAccessError(RuntimeError):
    pass


class LocalChrome:
    """Playwright sobre Chrome instalado localmente, sin proxy y sin sesión persistida."""

    def __init__(self, project_root: Path, config: dict[str, Any], headless: bool | None = None):
        self.project_root = project_root
        self.config = config
        self.headless = config.get("chrome_headless", True) if headless is None else headless
        self._playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.profile_dir: Path | None = None

    def __enter__(self) -> "LocalChrome":
        executable = Path(self.config["chrome_executable"])
        if not executable.exists():
            raise FileNotFoundError(f"Chrome local no existe: {executable}")
        work_dir = self.project_root / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = Path(tempfile.mkdtemp(prefix="chrome-session-", dir=work_dir))
        port = int(self.config["chrome_debug_port"])
        arguments = [
            str(executable),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={self.profile_dir}",
            "--no-proxy-server",
            "--disable-sync",
            "--disable-component-update",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1440,1100",
            "about:blank",
        ]
        if self.headless:
            arguments.insert(1, "--headless=new")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            arguments,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        endpoint = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{endpoint}/json/version", timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("Chrome local no expuso el puerto CDP en 127.0.0.1")
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.connect_over_cdp(endpoint)
        if not self.browser.contexts:
            raise RuntimeError("Chrome local no expuso un contexto navegable")
        self.context = self.browser.contexts[0]
        self.context.set_default_timeout(self.config["navigation_timeout_ms"])
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.profile_dir:
            marker = str(self.profile_dir.resolve()).casefold()
            related: list[psutil.Process] = []
            for process in psutil.process_iter(["name", "cmdline"]):
                try:
                    command = " ".join(process.info.get("cmdline") or []).casefold()
                    if (process.info.get("name") or "").casefold() == "chrome.exe" and marker in command:
                        related.append(process)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            for process in related:
                try:
                    process.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _, alive = psutil.wait_procs(related, timeout=3)
            for process in alive:
                try:
                    process.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        if self.profile_dir and self.profile_dir.exists():
            resolved = self.profile_dir.resolve()
            work_root = (self.project_root / "work").resolve()
            if work_root in resolved.parents and resolved.name.startswith("chrome-session-"):
                shutil.rmtree(resolved, ignore_errors=True)

    def new_public_page(self, url: str | None = None) -> Page:
        if not self.context:
            raise RuntimeError("El navegador no está abierto")
        page = self.context.pages[0] if self.context.pages else self.context.new_page()
        destination = url or self.config["base_url"]
        for attempt in range(2):
            try:
                if attempt == 0:
                    page.goto(destination, wait_until="domcontentloaded")
                else:
                    page.reload(wait_until="domcontentloaded")
                page.wait_for_function(
                    "document.body && document.body.innerText.trim().length > 0",
                    timeout=min(self.config["navigation_timeout_ms"], 30000),
                )
                break
            except PlaywrightTimeoutError:
                if attempt == 1:
                    raise PublicAccessError(
                        "La página pública de Ecuabet no terminó de cargar después "
                        "de una recarga controlada."
                    )
                page.wait_for_timeout(500)
        if "/deportes" in page.url:
            page.locator(
                'div[class*="EventBoxWrapper"], button[class*="SportOverviewTab"], '
                'div[class*="Competition"]'
            ).first.wait_for(
                state="attached",
                timeout=self.config["navigation_timeout_ms"],
            )
        page.wait_for_timeout(1000)
        self.assert_public_access(page)
        return page

    @staticmethod
    def assert_public_access(page: Page) -> None:
        body = page.locator("body").inner_text(timeout=30000).strip()
        if not body:
            raise PublicAccessError("Página vacía o cartelera deportiva no disponible.")
        for label, pattern in BLOCK_PATTERNS.items():
            if pattern.search(body):
                raise PublicAccessError(label)
        if re.search(r"debe(?:s)?\s+iniciar\s+sesión|login required", body, re.I):
            raise PublicAccessError("Solicitud obligatoria de inicio de sesión.")
        if not re.search(r"deporte|fútbol|futbol|partido|cuota|pronóstico", body, re.I):
            raise PublicAccessError("Página vacía o cartelera deportiva no disponible.")


@contextlib.contextmanager
def local_page(
    project_root: Path, config: dict[str, Any], url: str | None = None, headless: bool | None = None
) -> Iterator[Page]:
    with LocalChrome(project_root, config, headless=headless) as chrome:
        yield chrome.new_public_page(url)
