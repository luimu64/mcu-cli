"""Optional user configuration: ~/.config/mcu/config.toml

Everything has a working default; the file only exists to stop repeating flags.
CLI flags always win over the file, the file wins over built-in defaults.

    [defaults]
    mcu    = "atmega328p"
    freq   = "16000000"
    port   = "/dev/ttyUSB0"
    baud   = 115200
    arch   = "avr"
    build_type = "Release"
    simavr_prefix = "/usr/local"
    cc     = "cc"
    led    = ["D13"]          # applied by `mcu board` when no --led is given
    button = ["D2"]
"""

from __future__ import annotations

import os
from pathlib import Path

try:                                    # Python >= 3.11
    import tomllib
except ModuleNotFoundError:             # pragma: no cover
    tomllib = None

DEFAULTS = {
    "mcu": None,
    "freq": None,
    "port": None,
    "baud": 115200,
    "arch": "avr",
    "build_type": "Release",
    "simavr_prefix": "/usr/local",
    "cc": "cc",
    "led": [],
    "button": [],
    "press": [],
    "rx": [],
    "seconds": None,
}


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "mcu" / "config.toml"


def load(path: str | os.PathLike | None = None) -> dict:
    """Return the merged config (built-in defaults + the config file)."""
    cfg = dict(DEFAULTS)
    p = Path(path) if path else config_path()
    if not p.is_file():
        return cfg
    if tomllib is None:
        return cfg
    try:
        with open(p, "rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return cfg
    section = data.get("defaults", data)
    for key, value in section.items():
        if key in cfg:
            cfg[key] = value
    return cfg
