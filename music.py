"""Optional streaming music with a replaceable source catalog and player backend."""

from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
import signal
import subprocess
from typing import Callable


@dataclass(frozen=True)
class MusicSource:
    name: str
    url: str
    note: str = ""


@dataclass(frozen=True)
class MusicConfig:
    backend: str
    volume: int
    sources: tuple[MusicSource, ...]


def load_config(path: str) -> MusicConfig:
    """Read and validate the user-editable music catalog."""
    try:
        with open(path, encoding="utf-8") as config_file:
            raw = json.load(config_file)
    except OSError as exc:
        raise ValueError(f"Music config could not be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Music config is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Music config must be a JSON object")
    backend = str(raw.get("backend") or "auto").strip().lower()
    if backend not in {"auto", "mpv", "ffplay"}:
        raise ValueError("Music backend must be auto, mpv, or ffplay")
    volume = raw.get("volume", 55)
    if not isinstance(volume, int) or isinstance(volume, bool) or not 0 <= volume <= 100:
        raise ValueError("Music volume must be an integer from 0 to 100")

    sources: list[MusicSource] = []
    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("Music config needs a sources list")
    for index, entry in enumerate(raw_sources, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Music source {index} must be an object")
        name = str(entry.get("name") or "").strip()
        url = str(entry.get("url") or "").strip()
        note = str(entry.get("note") or "").strip()
        if not name or not url:
            raise ValueError(f"Music source {index} needs a name and URL")
        sources.append(MusicSource(name=name, url=url, note=note))
    if not sources:
        raise ValueError("Music config needs at least one source")
    return MusicConfig(backend=backend, volume=volume, sources=tuple(sources))


class MusicPlayer:
    """Own one external audio process behind a small, testable boundary."""

    def __init__(
        self,
        backend: str = "auto",
        volume: int = 55,
        *,
        which: Callable[[str], str | None] = shutil.which,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.backend = backend
        self.volume = volume
        self._which = which
        self._popen = popen
        self._process: subprocess.Popen | None = None
        self._source: MusicSource | None = None
        self._paused = False
        self._active_backend: str | None = None

    def configure(self, backend: str, volume: int) -> None:
        """Apply settings to the next stream without interrupting this one."""
        self.backend = backend
        self.volume = volume

    @property
    def active(self) -> bool:
        if self._process is not None and self._process.poll() is not None:
            self._clear()
        return self._process is not None

    @property
    def paused(self) -> bool:
        return self.active and self._paused

    @property
    def source(self) -> MusicSource | None:
        return self._source if self.active else None

    @property
    def active_backend(self) -> str | None:
        return self._active_backend if self.active else None

    def _resolve_backend(self) -> tuple[str, str]:
        candidates = ("mpv", "ffplay") if self.backend == "auto" else (self.backend,)
        for name in candidates:
            executable = self._which(name)
            if executable:
                return name, executable
        wanted = "mpv or ffplay" if self.backend == "auto" else self.backend
        raise RuntimeError(f"No music player found; install {wanted} or change the Ward music config")

    def _command(self, backend: str, executable: str, url: str) -> list[str]:
        if backend == "mpv":
            return [
                executable,
                "--no-video",
                "--really-quiet",
                "--force-window=no",
                f"--volume={self.volume}",
                url,
            ]
        return [
            executable,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
            "-volume",
            str(self.volume),
            url,
        ]

    def play(self, source: MusicSource) -> str:
        self.stop()
        backend, executable = self._resolve_backend()
        try:
            self._process = self._popen(
                self._command(backend, executable, source.url),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self._clear()
            raise RuntimeError(f"Music player could not start: {exc}") from exc
        self._source = source
        self._paused = False
        self._active_backend = backend
        return backend

    def toggle_pause(self) -> bool:
        if not self.active or self._process is None:
            raise RuntimeError("No music is playing")
        pause_signal = getattr(signal, "SIGSTOP", None)
        resume_signal = getattr(signal, "SIGCONT", None)
        if pause_signal is None or resume_signal is None:
            raise RuntimeError("Pause is not supported by this operating system")
        self._paused = not self._paused
        self._process.send_signal(pause_signal if self._paused else resume_signal)
        return self._paused

    def stop(self) -> None:
        process = self._process
        if process is None:
            self._clear()
            return
        if process.poll() is None:
            try:
                if self._paused:
                    resume_signal = getattr(signal, "SIGCONT", None)
                    if resume_signal is not None:
                        process.send_signal(resume_signal)
                process.terminate()
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self._clear()

    def _clear(self) -> None:
        self._process = None
        self._source = None
        self._paused = False
        self._active_backend = None
