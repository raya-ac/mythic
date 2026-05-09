"""Supervised plugin execution."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MANIFEST_NAMES = ("mythic-plugin.json", "plugin.json")


@dataclass(frozen=True)
class PluginManifest:
    """Static capability declaration for a runtime plugin."""

    name: str
    runtime: str
    entrypoint: list[str]
    version: str = "0.1.0"
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        entrypoint = data.get("entrypoint")
        if isinstance(entrypoint, str):
            entrypoint = [entrypoint]
        if not isinstance(entrypoint, list) or not all(isinstance(item, str) for item in entrypoint):
            raise ValueError("plugin entrypoint must be a string or list of strings")

        name = data.get("name")
        runtime = data.get("runtime")
        if not isinstance(name, str) or not name:
            raise ValueError("plugin name is required")
        if not isinstance(runtime, str) or not runtime:
            raise ValueError("plugin runtime is required")

        return cls(
            name=name,
            runtime=runtime,
            entrypoint=entrypoint,
            version=str(data.get("version", "0.1.0")),
            description=str(data.get("description", "")),
            capabilities=list(data.get("capabilities", [])),
            timeout_seconds=float(data.get("timeout_seconds", 30.0)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "runtime": self.runtime,
            "entrypoint": self.entrypoint,
            "version": self.version,
            "description": self.description,
            "capabilities": self.capabilities,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class PluginResult:
    """Captured result from a supervised plugin run."""

    plugin: PluginManifest
    returncode: int
    stdout: str
    stderr: str
    elapsed_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "plugin": self.plugin.to_dict(),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "elapsed_ms": self.elapsed_ms,
            "timed_out": self.timed_out,
        }


class PluginHost:
    """Loads plugin manifests and runs them with basic supervision."""

    def load_manifest(self, plugin_path: str | Path) -> PluginManifest:
        path = Path(plugin_path)
        manifest_path = self._find_manifest(path)
        return PluginManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))

    def run(
        self,
        plugin_path: str | Path,
        *,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> PluginResult:
        path = Path(plugin_path)
        manifest = self.load_manifest(path)
        timeout = timeout_seconds if timeout_seconds is not None else manifest.timeout_seconds
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                manifest.entrypoint,
                cwd=path if path.is_dir() else path.parent,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return PluginResult(
                plugin=manifest,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                elapsed_ms=elapsed_ms,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return PluginResult(
                plugin=manifest,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                elapsed_ms=elapsed_ms,
                timed_out=True,
            )

    def _find_manifest(self, plugin_path: Path) -> Path:
        if plugin_path.is_file():
            return plugin_path
        for name in MANIFEST_NAMES:
            candidate = plugin_path / name
            if candidate.exists():
                return candidate
        expected = ", ".join(MANIFEST_NAMES)
        raise FileNotFoundError(f"plugin manifest not found in {plugin_path}; expected {expected}")
