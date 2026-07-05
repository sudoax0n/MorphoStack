"""System diagnostics used by `morphostack doctor`."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any


def collect_diagnostics() -> dict[str, Any]:
    cpu_count = os.cpu_count()
    disk = shutil.disk_usage(Path.cwd().anchor or Path.cwd())
    diagnostics: dict[str, Any] = {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "hardware": {
            "cpu_count": cpu_count,
            "ram_bytes": get_total_ram_bytes(),
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
    }
    return diagnostics


def get_total_ram_bytes() -> int | None:
    try:
        import psutil
    except Exception:
        return None
    return int(psutil.virtual_memory().total)


def format_diagnostics(diagnostics: dict[str, Any], as_json: bool = False) -> str:
    if as_json:
        return json.dumps(diagnostics, indent=2, sort_keys=True)

    lines = [
        "MorphoStack Doctor",
        "==================",
        "",
        f"OS: {diagnostics['platform']['system']} {diagnostics['platform']['release']}",
        f"Machine: {diagnostics['platform']['machine']}",
        f"Processor: {diagnostics['platform']['processor'] or 'Unknown'}",
        f"CPU cores: {diagnostics['hardware']['cpu_count'] or 'Unknown'}",
        f"RAM: {format_bytes(diagnostics['hardware']['ram_bytes'])}",
        f"Disk free: {format_bytes(diagnostics['disk']['free_bytes'])}",
        f"Python: {diagnostics['python']['version']}",
        f"Python executable: {diagnostics['python']['executable']}",
        "",
        "Commands:",
    ]

    for name, command in diagnostics.get("commands", {}).items():
        if isinstance(command, dict):
            available = bool(command.get("available"))
            version = str(command.get("version") or "version unknown")
            path = str(command.get("path") or "not found")
            lines.append(f"  {status_icon(available)} {name}: {version} ({path})")
        else:
            lines.append(f"  {status_icon(command)} {name}")

    lines.append("")
    lines.append("Dependencies:")
    for group, deps in diagnostics.get("dependencies", {}).items():
        lines.append(f"  {group}:")
        for name, available in deps.items():
            lines.append(f"    {status_icon(available)} {name}")

    web = diagnostics.get("web")
    if isinstance(web, dict):
        lines.append("")
        lines.append("Web app:")
        lines.append(f"  Path: {web.get('path')}")
        lines.append(f"  {status_icon(bool(web.get('package_json')))} package.json")
        lines.append(f"  {status_icon(bool(web.get('node_modules')))} node_modules")

    return "\n".join(lines)


def status_icon(value: bool) -> str:
    return "OK" if value else "MISSING"


def format_bytes(value: int | None) -> str:
    if value is None:
        return "Unknown"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"
