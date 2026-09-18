"""Small process / parsing / terminal helpers shared by every command."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys

# --------------------------------------------------------------------------
# terminal output
# --------------------------------------------------------------------------

def _enable_colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR_FORCE"):
        return True
    return sys.stdout.isatty()


if _enable_colour():
    C_OK, C_WARN, C_ERR, C_DIM, C_OFF = (
        "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m")
else:
    C_OK = C_WARN = C_ERR = C_DIM = C_OFF = ""


def die(msg: str, code: int = 1):
    print(f"{C_ERR}mcu: {msg}{C_OFF}", file=sys.stderr)
    sys.exit(code)


def info(msg: str):
    print(msg)


def step(msg: str):
    print(f"{C_DIM}==>{C_OFF} {msg}")


def ok(msg: str):
    print(f"{C_OK}ok{C_OFF}  {msg}")


def warn(msg: str):
    print(f"{C_WARN}warn{C_OFF} {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------

def have(tool: str):
    return shutil.which(tool)


_PKG_MANAGERS = [
    ("pacman", "sudo pacman -S"),
    ("apt-get", "sudo apt install"),
    ("dnf", "sudo dnf install"),
    ("zypper", "sudo zypper install"),
    ("apk", "sudo apk add"),
    ("brew", "brew install"),
]

# distro-specific package names that differ from the binary name
_PKG_ALIASES = {
    "avr-gcc": {"apt-get": "gcc-avr", "dnf": "avr-gcc", "brew": "avr-gcc"},
    "avr-gdb": {"apt-get": "gdb-avr", "brew": "avr-gdb"},
    "avr-objcopy": {"apt-get": "binutils-avr", "brew": "avr-binutils"},
    "avr-size": {"apt-get": "binutils-avr", "brew": "avr-binutils"},
    # Debian/Ubuntu keep the bare-metal C library in its own package: without it
    # the link fails with "cannot find -lc"
    "arm-none-eabi-gcc": {"apt-get": "gcc-arm-none-eabi libnewlib-arm-none-eabi",
                          "brew": "arm-none-eabi-gcc"},
    "arm-none-eabi-gdb": {"apt-get": "gdb-arm-none-eabi", "brew": "arm-none-eabi-gdb"},
    "arm-none-eabi-size": {"apt-get": "binutils-arm-none-eabi"},
    "arm-none-eabi-objcopy": {"apt-get": "binutils-arm-none-eabi"},
    "simavr": {"apt-get": "simavr", "brew": "simavr"},
    "qemu-system-avr": {"apt-get": "qemu-system-arm", "brew": "qemu"},
    "picocom": {"apt-get": "picocom", "brew": "picocom"},
    "ninja": {"apt-get": "ninja-build", "brew": "ninja"},
    "avr-libc": {"apt-get": "avr-libc"},
    "pyocd": {"*": "pipx install pyocd"},
    "probe-rs": {"*": "cargo install probe-rs-tools"},
}


def arm_newlib_ok(compiler="arm-none-eabi-gcc") -> bool:
    """True when the bare-metal C library is reachable by the ARM compiler.

    Debian/Ubuntu ship gcc-arm-none-eabi without newlib; the linker then fails
    with `cannot find -lc`. `-print-file-name` echoes the name unchanged when it
    cannot resolve it, which is the cheapest reliable probe.
    """
    path = have(compiler)
    if not path:
        return False
    try:
        out = subprocess.run([path, "-print-file-name=libc.a"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, timeout=20).stdout.strip()
    except Exception:
        return False
    return "/" in out


def install_hint(tool: str) -> str:
    """A best-effort install hint for the local package manager."""
    for mgr, cmd in _PKG_MANAGERS:
        if shutil.which(mgr):
            alias = _PKG_ALIASES.get(tool, {})
            name = alias.get(mgr, alias.get("*", tool))
            if name.startswith(("pipx", "cargo")):
                return name
            return f"{cmd} {name}"
    generic = _PKG_ALIASES.get(tool, {}).get("*")
    return generic or f"install '{tool}' with your package manager"


def need(tool: str, hint: str | None = None, why: str | None = None):
    """Die with a useful hint when a required tool is missing."""
    path = have(tool)
    if path:
        return path
    extra = f"\n     ({why})" if why else ""
    die(f"'{tool}' not found in PATH.\n     install: {hint or install_hint(tool)}{extra}")


def require(tool: str, dry: bool = False, hint: str | None = None,
            why: str | None = None):
    """Like need(), but a dry run only previews commands, so it never demands
    the toolchain to be installed."""
    if dry:
        return None
    return need(tool, hint=hint, why=why)


def run(cmd, dry=False, cwd=None, capture=False, check=True, env=None):
    """Run a command, streaming output unless `capture` is set."""
    shown = " ".join(str(c) for c in cmd)
    if dry:
        print(f"{C_DIM}   $ {shown}{C_OFF}")
        return 0, ""
    if os.environ.get("MCU_VERBOSE"):
        print(f"{C_DIM}   $ {shown}{C_OFF}")
    try:
        if capture:
            p = subprocess.run(cmd, cwd=cwd, env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            out = p.stdout or ""
            if check and p.returncode != 0:
                die(f"command failed ({p.returncode}): {shown}\n{out}")
            return p.returncode, out
        p = subprocess.run(cmd, cwd=cwd, env=env)
        if check and p.returncode != 0:
            die(f"command failed ({p.returncode}): {shown}")
        return p.returncode, ""
    except FileNotFoundError:
        die(f"cannot execute '{cmd[0]}'")
    except KeyboardInterrupt:
        print()
        die("interrupted", 130)


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

_UNITS = {"": 1.0, "ms": 1.0, "s": 1000.0, "m": 60000.0}


def parse_ms(text, default_unit_ms: float = 1.0) -> float:
    """'500' -> 500 ms, '150ms' -> 150, '1.5s' -> 1500, '2m' -> 120000."""
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(ms|s|m)?\s*", str(text))
    if not m:
        die(f"cannot parse duration '{text}' (use 500, 150ms, 1.5s, 2m)")
    value, unit = float(m.group(1)), m.group(2) or ""
    return value * (_UNITS[unit] if unit else default_unit_ms)


# Arduino Uno/Nano style pin labels -> (AVR port letter, bit)
ARDUINO_LABELS = {
    **{f"D{i}": ("D", i) for i in range(8)},            # D0..D7  = PD0..PD7
    **{f"D{i}": ("B", i - 8) for i in range(8, 14)},    # D8..D13 = PB0..PB5
    **{f"A{i}": ("C", i) for i in range(6)},            # A0..A5  = PC0..PC5
}

# PCINT group per port: PB -> PCINT0..7, PC -> 8..15, PD -> 16..23
PCINT_GROUP = {"B": 0, "C": 1, "D": 2}


def parse_portpin(spec):
    """'PB5' / 'B5' / 'PB:5' / 'D13' / 'A0' -> (port letter, bit)."""
    s = str(spec).upper().strip()
    if s in ARDUINO_LABELS:
        return ARDUINO_LABELS[s]
    m = re.fullmatch(r"(?:P)?([A-L])\s*:?\s*([0-7])", s)
    if not m:
        die(f"cannot parse port pin '{spec}' "
            f"(use PB5, D13, A0 or the explicit form PB:5)")
    return m.group(1), int(m.group(2))


def parse_label(spec, port, bit) -> str:
    """Keep Arduino-style labels (D13), otherwise name the port pin."""
    s = str(spec).upper().strip()
    return s if s in ARDUINO_LABELS else f"P{port}{bit}"


def pcint_for(port: str, bit: int):
    """(group, PCINT number) for a port/bit, e.g. PD2 -> (2, 18)."""
    if port not in PCINT_GROUP:
        die(f"port P{port} has no PCINT group (use a B, C or D pin)")
    group = PCINT_GROUP[port]
    return group, group * 8 + bit


def c_string(s) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def human_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    return f"{ms:.1f} ms"


# --------------------------------------------------------------------------
# serial ports
# --------------------------------------------------------------------------

def serial_ports():
    """Best-effort list of usable serial devices (Linux/macOS)."""
    found = []
    patterns = ["/dev/serial/by-id/*", "/dev/ttyUSB*", "/dev/ttyACM*",
                "/dev/cu.usbserial*", "/dev/cu.usbmodem*", "/dev/tty.usbserial*",
                "/dev/tty.usbmodem*"]
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            resolved = os.path.realpath(p) if "by-id" in pat else p
            if resolved not in found:
                found.append(resolved)
    return found


def pick_port(explicit=None, dry=False) -> str:
    if explicit:
        if not os.path.exists(explicit) and not dry:
            die(f"serial port {explicit} does not exist "
                f"(found: {', '.join(serial_ports()) or 'none'})")
        return explicit
    ports = serial_ports()
    if not ports:
        if dry:
            return "/dev/ttyUSB0"
        die("no serial port found — is the board plugged in?\n"
            "     ports looked at: /dev/ttyUSB*, /dev/ttyACM*, /dev/serial/by-id/*")
    if len(ports) > 1:
        warn(f"several ports, using {ports[0]} (override with --port)")
    return ports[0]
