"""Cross-platform virtual-memory diagnostics and safe configuration plans."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
# Only resolved, fixed executables are used; shell execution is never enabled.
import subprocess  # nosec B404
from dataclasses import asdict, dataclass
from pathlib import Path

GIB = 1024**3
LINUX_SWAPFILE = Path("/var/lib/amosclaud/swapfile")


class VirtualMemoryError(RuntimeError):
    """Raised when a requested host-memory operation is unsafe or unsupported."""


@dataclass(frozen=True)
class MemoryPlan:
    system: str
    physical_bytes: int
    swap_total_bytes: int
    swap_free_bytes: int
    recommended_swap_bytes: int
    managed_by_os: bool
    action: str


def recommended_swap_bytes(physical_bytes: int) -> int:
    """Return a conservative server-oriented recommendation, capped at 16 GiB."""
    if physical_bytes <= 0:
        raise ValueError("physical_bytes must be positive")
    physical_gib = physical_bytes / GIB
    if physical_gib <= 4:
        swap_gib = 2 * physical_gib
    elif physical_gib <= 16:
        swap_gib = physical_gib
    else:
        swap_gib = 8
    return int(max(2, min(16, round(swap_gib))) * GIB)


def _linux_memory() -> tuple[int, int, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        name, raw = line.split(":", 1)
        values[name] = int(raw.strip().split()[0]) * 1024
    return values["MemTotal"], values.get("SwapTotal", 0), values.get("SwapFree", 0)


def _posix_memory() -> tuple[int, int, int]:
    page_size = os.sysconf("SC_PAGE_SIZE")
    physical = page_size * os.sysconf("SC_PHYS_PAGES")
    return physical, 0, 0


def _windows_memory() -> tuple[int, int, int]:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_pagefile", ctypes.c_ulonglong),
            ("available_pagefile", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise VirtualMemoryError("Windows could not report its memory status")
    page_total = max(0, status.total_pagefile - status.total_physical)
    page_free = min(page_total, status.available_pagefile)
    return status.total_physical, page_total, page_free


def inspect_memory() -> MemoryPlan:
    system = platform.system()
    if system == "Linux":
        physical, swap_total, swap_free = _linux_memory()
    elif system == "Windows":
        physical, swap_total, swap_free = _windows_memory()
    else:
        physical, swap_total, swap_free = _posix_memory()
    recommendation = recommended_swap_bytes(physical)
    managed = system in {"Darwin", "Windows"}
    if managed:
        action = f"Use the {system} installer to review the OS-managed pagefile or swap policy."
    elif swap_total >= recommendation:
        action = (
            "Existing swap meets the Amosclaud recommendation; no change is needed."
        )
    else:
        action = f"Create {recommendation // GIB} GiB at {LINUX_SWAPFILE} with explicit approval."
    return MemoryPlan(
        system=system,
        physical_bytes=physical,
        swap_total_bytes=swap_total,
        swap_free_bytes=swap_free,
        recommended_swap_bytes=recommendation,
        managed_by_os=managed,
        action=action,
    )


def apply_linux_swap(size_bytes: int) -> None:
    """Create a fixed-location swapfile. Caller must explicitly opt in as root."""
    if platform.system() != "Linux":
        raise VirtualMemoryError("Automatic swap creation is supported only on Linux")
    if os.geteuid() != 0:
        raise VirtualMemoryError("Run with sudo to configure host virtual memory")
    size_gib = size_bytes // GIB
    if size_gib < 2 or size_gib > 16:
        raise VirtualMemoryError("Swap size must be between 2 and 16 GiB")
    if LINUX_SWAPFILE.exists():
        raise VirtualMemoryError(f"Refusing to replace existing {LINUX_SWAPFILE}")
    commands = {
        name: shutil.which(name)
        for name in ("fallocate", "mkswap", "swapon", "swapoff")
    }
    for command, executable in commands.items():
        if not executable:
            raise VirtualMemoryError(f"Required host command is missing: {command}")
    LINUX_SWAPFILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        subprocess.run(
            [commands["fallocate"], "-l", f"{size_gib}G", str(LINUX_SWAPFILE)],
            check=True,
        )  # nosec B603
        LINUX_SWAPFILE.chmod(0o600)
        subprocess.run(
            [commands["mkswap"], str(LINUX_SWAPFILE)], check=True
        )  # nosec B603
        subprocess.run(
            [commands["swapon"], str(LINUX_SWAPFILE)], check=True
        )  # nosec B603
        fstab = Path("/etc/fstab")
        entry = f"{LINUX_SWAPFILE} none swap sw 0 0"
        current = fstab.read_text(encoding="utf-8") if fstab.exists() else ""
        if entry not in current.splitlines():
            with fstab.open("a", encoding="utf-8") as handle:
                handle.write(f"\n{entry}\n")
    except Exception:
        subprocess.run(
            [commands["swapoff"], str(LINUX_SWAPFILE)], check=False
        )  # nosec B603
        LINUX_SWAPFILE.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(prog="amosclaud-memory")
    parser.add_argument(
        "command", choices=["status", "apply"], nargs="?", default="status"
    )
    parser.add_argument("--size-gib", type=int)
    parser.add_argument(
        "--yes", action="store_true", help="Confirm a privileged host change"
    )
    args = parser.parse_args()
    plan = inspect_memory()
    if args.command == "apply":
        if not args.yes:
            parser.error(
                "apply requires --yes because it changes host storage and /etc/fstab"
            )
        apply_linux_swap((args.size_gib or plan.recommended_swap_bytes // GIB) * GIB)
        plan = inspect_memory()
    print(json.dumps(asdict(plan), indent=2))


if __name__ == "__main__":
    main()
