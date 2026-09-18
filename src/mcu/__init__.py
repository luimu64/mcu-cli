"""mcu — one CLI for the embedded workflow (AVR + Cortex-M, no vendor IDE)."""

from __future__ import annotations

__all__ = ["main", "__version__"]

try:
    from importlib.metadata import PackageNotFoundError, version as _version
    try:
        __version__ = _version("mcu-cli")
    except PackageNotFoundError:                        # running from a checkout
        __version__ = "1.0.0"
except Exception:                                       # pragma: no cover
    __version__ = "1.0.0"


def main(argv=None) -> int:
    """Entry point (also exported as the `mcu` console script)."""
    from .cli import main as _main
    return _main(argv)
