"""Small process / parsing / terminal helpers shared by every command."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from typing import NoReturn

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


def die(msg: str, code: int = 1) -> NoReturn:
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


def run(cmd, dry=False, cwd=None, capture=False, check=True, env=None,
        stdout_path=None):
    """Run a command, streaming output unless `capture` is set.

    `stdout_path` redirects stdout into a file (no shell involved) — needed by
    simavr builds that only emit their VCD on stdout.
    """
    shown = " ".join(str(c) for c in cmd)
    if dry:
        suffix = f" > {stdout_path}" if stdout_path else ""
        print(f"{C_DIM}   $ {shown}{suffix}{C_OFF}")
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
        if stdout_path:
            with open(stdout_path, "w") as fh:
                p = subprocess.run(cmd, cwd=cwd, env=env, stdout=fh)
        else:
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
# simavr capabilities
# --------------------------------------------------------------------------

# Optional simavr flags, with the value each probe hands over. simavr has no
# --version and --list-cores exits 1, so the only reliable question is
# behavioural: give it `<flag> <value> <firmware that cannot exist>` and see which
# name it complains about. If it fails on the VALUE, the flag does not exist and
# the value was read as a firmware file name.
_SIMAVR_PROBES = {
    "gdb_port": ("-g", "54321"),                 # `-g <port>`; 1.6 wants bare -g
    "signal":   ("-at", "PROBE=sram8@0x25"),     # VCD signal selection
    "output":   ("-o", "probe.vcd"),             # VCD file instead of stdout
}
_SIMAVR_MODERN = set(_SIMAVR_PROBES)
_simavr_cache = {}


def simavr_caps(simavr="simavr") -> set:
    """Flags this simavr build accepts, e.g. {'gdb_port', 'signal', 'output'}.

    Debian/Ubuntu still ship simavr 1.6, which knows none of them: it ignores the
    flag and then treats its value as the firmware to load, so `mcu debug` dies
    with "gdbserver exited immediately" and `mcu trace` tries to load the .vcd.
    A modern (source-built) simavr accepts all three.

    Probing never opens a socket or waits: the missing-firmware error comes first.
    `MCU_SIMAVR_FLAGS` overrides the result for a build the probe misjudges.
    """
    override = os.environ.get("MCU_SIMAVR_FLAGS")
    if override is not None:
        return {f.strip() for f in override.split(",") if f.strip()}

    path = shutil.which(simavr) or simavr
    if path in _simavr_cache:
        return _simavr_cache[path]

    missing = os.path.join(os.sep, "nonexistent-mcu-probe.elf")
    caps = set()
    for name, (flag, value) in _SIMAVR_PROBES.items():
        try:
            p = subprocess.run([path, flag, value, missing], text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=10)
            out = p.stdout or ""
        except Exception:
            out = ""
        if missing in out and value not in out:
            caps.add(name)                        # the flag swallowed its value
        elif value in out:
            pass                                  # flag unknown: value 404'd
        else:
            caps.add(name)                        # unknown output: assume modern
    _simavr_cache[path] = caps
    return caps


def simavr_note(caps) -> str:
    """One-line capability summary for `mcu doctor`."""
    if not caps:
        return "no -g <port>/-at/-o (simavr 1.6: build from source for traces)"
    if "signal" in caps and "output" in caps:
        return "traces ok (-at/-o)"
    return " + ".join(sorted(caps))


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

# AVR8X — megaAVR 0-series and tinyAVR 0/1/2-series. Different core from classic
# AVR8: PORT_t registers instead of PORTB bytes, per-pin port interrupts, USART0
# instead of UCSR0, UPDI instead of ISP, and fuse0..fuse8 instead of
# lfuse/hfuse/efuse. Names are the lowercase avr-gcc/CMake spellings.
AVR8X_PARTS = frozenset("""
    atmega808 atmega809 atmega1608 atmega1609 atmega3208 atmega3209
    atmega4808 atmega4809
    attiny202 attiny204 attiny402 attiny404 attiny406 attiny412 attiny414
    attiny416 attiny417 attiny212 attiny214
    attiny804 attiny806 attiny807 attiny814 attiny816 attiny817
    attiny1604 attiny1606 attiny1607 attiny1614 attiny1616 attiny1617
    attiny424 attiny426 attiny427 attiny824 attiny826 attiny827
    attiny1624 attiny1626 attiny1627 attiny3216 attiny3217 attiny3224
    attiny3226 attiny3227
""".split())


def is_avr8x(mcu) -> bool:
    """True for megaAVR 0-series / tinyAVR 0,1,2-series parts."""
    name = str(mcu or "").strip().lower().replace("_", "")
    if name.endswith("auto"):                 # ATtiny1614auto is the same silicon
        name = name[:-4]
    return name in AVR8X_PARTS


# megaAVR 0-series (4808/4809/…) pack PORTA..PORTF; tinyAVR 0/1/2-series PORTA..PORTC
MEGA_PORTS = ("A", "B", "C", "D", "E", "F")
TINY_PORTS = ("A", "B", "C")


def avr8x_ports(mcu) -> tuple:
    """Port letters that exist on this AVR8X part (PA0..PF5 on the megaAVR 0)."""
    name = str(mcu or "").strip().lower()
    return MEGA_PORTS if name.startswith("atmega") else TINY_PORTS


def parse_portpin(spec, ports=None):
    """'PB5' / 'B5' / 'PB:5' / 'D13' / 'A0' -> (port letter, bit).

    `ports` restricts the allowed port letters (AVR8X passes its own set, since
    every pin there is individually interrupt-capable and PORTF exists on the
    megaAVR 0-series); None keeps the classic Arduino-label behaviour.
    """
    s = str(spec).upper().strip()
    if s in ARDUINO_LABELS:
        return ARDUINO_LABELS[s]
    m = re.fullmatch(r"(?:P)?([A-L])\s*:?\s*([0-7])", s)
    if not m:
        die(f"cannot parse port pin '{spec}' "
            f"(use PB5, D13, A0 or the explicit form PB:5)")
    port, bit = m.group(1), int(m.group(2))
    if ports and port not in ports:
        die(f"that part has ports {', '.join('P' + p for p in ports)} — not P{port}")
    return port, bit


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
