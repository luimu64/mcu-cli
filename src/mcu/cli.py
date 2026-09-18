"""Argument parsing and dispatch."""

from __future__ import annotations

import argparse
import os
import sys
import textwrap

from . import __version__
from . import config as cfgmod
from . import ops

EPILOG = """\
examples:
  mcu new blink --led D13 --button D2        scaffold a project
  mcu build && mcu flash && mcu monitor      the normal hardware loop
  mcu board --led D13 --button D2 --press 1.5s:150ms --rx 1.2s:abc --seconds 8
  mcu debug -x 'break main' -x continue -x bt --batch
  mcu trace --seconds 3 -o ports.vcd

peripherals in simulation: --led/--button take Arduino labels (D13, A0) or raw
port pins (PB5). Durations accept 500, 150ms, 1.5s, 2m.
"""


def add_common(p, suppress=False):
    """Common flags. `suppress=True` on subparsers so that a value given before
    the subcommand (`mcu -C dir build`) is not overwritten by the subparser's
    default."""
    default = argparse.SUPPRESS if suppress else None
    p.add_argument("-C", "--project", metavar="DIR", default=default,
                   help="project directory (default: search upwards from cwd)")
    p.add_argument("-n", "--dry-run", action="store_true",
                   default=argparse.SUPPRESS if suppress else False,
                   help="print the commands instead of running them")
    p.add_argument("--verbose", action="store_true",
                   default=argparse.SUPPRESS if suppress else False,
                   help="echo every command")


def add_sim_select(p):
    p.add_argument("--mcu", help="override the MCU (simavr -m)")
    p.add_argument("--freq", help="override the clock in Hz")
    p.add_argument("--simavr-prefix", help="simavr install prefix (default /usr/local)")
    p.add_argument("-S", "--firmware", metavar="FILE",
                   help="firmware to run (default: the project's build output)")


def add_peripherals(p):
    p.add_argument("--led", action="append", metavar="PIN",
                   help="observe an output pin as an LED (repeatable)")
    p.add_argument("--button", action="append", metavar="PIN",
                   help="attach a button driving this pin (repeatable)")
    p.add_argument("--press", action="append", metavar="[BTN:]AT:HOLD",
                   help="scripted press, e.g. 1.5s:150ms (repeatable)")
    p.add_argument("--rx", action="append", metavar="AT:TEXT",
                   help="inject serial input, e.g. 1.2s:abc (repeatable)")
    p.add_argument("--no-uart", action="store_true", help="do not print UART output")
    p.add_argument("--no-keys", dest="keys", action="store_false",
                   help="disable the interactive keys")
    p.set_defaults(keys=True)
    p.add_argument("--cc", help="host C compiler for the harness (default: cc)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mcu",
        description="one CLI for the embedded workflow: scaffold, build, flash, "
                    "monitor, simulate with peripherals, debug, trace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(EPILOG))
    ap.add_argument("-V", "--version", action="version", version=f"mcu {__version__}")
    add_common(ap)                      # accepted before the subcommand too
    sub = ap.add_subparsers(dest="cmd", metavar="<command>")

    p = sub.add_parser("doctor", help="toolchain + device inventory")
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_doctor)

    p = sub.add_parser("list", help="MCUs / peripheral parts known to simavr")
    p.add_argument("what", nargs="?", default="cores", choices=["cores", "parts"])
    p.add_argument("--simavr-prefix", help="simavr install prefix")
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_list)

    p = sub.add_parser("new", help="scaffold a project")
    p.add_argument("path")
    p.add_argument("--name", help="CMake project/target name (default: dirname)")
    p.add_argument("--arch", choices=["avr", "arm"], help="target family (default avr)")
    p.add_argument("--mcu", help="AVR part (default atmega328p)")
    p.add_argument("--freq", help="CPU clock in Hz (default 16000000)")
    p.add_argument("--baud", type=int, help="UART baud for the demo (default 115200)")
    p.add_argument("--led", default=None, help="LED pin for the demo (default D13/PB5)")
    p.add_argument("--button", default=None, help="button pin (default D2/PD2)")
    p.add_argument("--cpu", default="cortex-m0plus",
                   help="ARM: -mcpu value (cortex-m4, cortex-m0plus, ...)")
    p.add_argument("--float-abi", default="-mfloat-abi=soft")
    p.add_argument("--chip", help="ARM: probe-rs chip name for .zed/debug.json")
    p.add_argument("--flash", default="256K", help="ARM: FLASH size in the linker script")
    p.add_argument("--ram", default="32K", help="ARM: RAM size in the linker script")
    p.add_argument("--flash-origin", default="0x00000000")
    p.add_argument("--ram-origin", default="0x20000000")
    p.add_argument("--force", action="store_true", help="write into a non-empty dir")
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_new)

    p = sub.add_parser("build", help="cmake configure + build")
    p.add_argument("--build-type", help="CMake build type (default Release)")
    p.add_argument("--reconfigure", action="store_true",
                   help="re-run the cmake configure step")
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_build)

    p = sub.add_parser("clean", help="remove build outputs")
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_clean)

    p = sub.add_parser("size", help="flash/RAM usage of the built ELF")
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_size)

    p = sub.add_parser("flash", help="upload to the board")
    p.add_argument("--method", default="auto",
                   choices=["auto", "bootloader", "usbasp", "icsp"],
                   help="bootloader = USB serial; usbasp/icsp = a real programmer")
    p.add_argument("--port", help="serial port (autodetected)")
    p.add_argument("--baud", type=int,
                   help="bootloader baud (official Nano 57600, most clones 115200)")
    p.add_argument("--part", help="avrdude part (default derived from the project MCU)")
    p.add_argument("-f", "--file", help="file to flash (default build/*.hex)")
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_flash)

    p = sub.add_parser("monitor", help="serial console")
    p.add_argument("--port", help="serial port (autodetected)")
    p.add_argument("--baud", type=int, help="baud (default 115200)")
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_monitor)

    p = sub.add_parser("sim", help="run the firmware under simavr")
    p.add_argument("--seconds", type=float, help="stop after N simulated seconds")
    p.add_argument("--gdb", nargs="?", const=1234, type=int, metavar="PORT",
                   help="also listen for gdb")
    p.add_argument("--trace", metavar="FILE.vcd", help="write a VCD trace")
    p.add_argument("-at", "--signal", action="append",
                   help="VCD signal spec, e.g. PORTB=sram8@0x25 (repeatable)")
    add_sim_select(p)
    add_peripherals(p)
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_sim)

    p = sub.add_parser("board", help="simavr + LEDs, buttons and serial I/O")
    p.add_argument("--seconds", type=float, help="stop after N simulated seconds")
    add_sim_select(p)
    add_peripherals(p)
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_board)

    p = sub.add_parser("debug", help="breakpoints, stepping, registers")
    p.add_argument("-x", "--exe", action="append", metavar="CMD",
                   help="gdb command to run (repeatable)")
    p.add_argument("--batch", action="store_true",
                   help="run the -x list then detach (no interactive shell)")
    p.add_argument("--gdb-port", type=int, default=1234)
    p.add_argument("--timeout", type=int, default=60,
                   help="seconds before a --batch session is killed")
    p.add_argument("--hw", action="store_true",
                   help="debug a real ARM target via pyocd instead of simavr")
    add_sim_select(p)
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_debug)

    p = sub.add_parser("trace", help="VCD signal trace of the simulation")
    p.add_argument("-o", "--output", metavar="FILE.vcd")
    p.add_argument("--seconds", type=float, help="stop after N simulated seconds")
    p.add_argument("-at", "--signal", action="append",
                   help="signal spec, e.g. PB5=portpin@0x5/0x42 (repeatable)")
    add_sim_select(p)
    add_common(p, suppress=True)
    p.set_defaults(func=ops.cmd_trace)

    return ap


# flags that fall back to the config file when not given on the command line
_CONFIG_KEYS = ("mcu", "freq", "port", "baud", "build_type", "arch",
                "simavr_prefix", "cc", "seconds", "led", "button", "press", "rx")


def apply_config(args, cfg: dict):
    for key in _CONFIG_KEYS:
        if hasattr(args, key) and getattr(args, key) in (None, [], False):
            value = cfg.get(key)
            if value in (None, [], ""):
                continue
            setattr(args, key, value)


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 1

    cfg = cfgmod.load()
    apply_config(args, cfg)

    # flags may have been given before the subcommand (SUPPRESS keeps them out of
    # the namespace otherwise), so make sure they always exist
    for flag, fallback in (("project", None), ("dry_run", False), ("verbose", False)):
        if not hasattr(args, flag):
            setattr(args, flag, fallback)

    # concrete fallbacks after config
    if getattr(args, "arch", None) in (None, ""):
        args.arch = "avr"
    if getattr(args, "mcu", None) in (None, ""):
        args.mcu = "atmega328p"
    if getattr(args, "freq", None) in (None, ""):
        args.freq = "16000000"
    if getattr(args, "baud", None) in (None, ""):
        args.baud = 115200
    if getattr(args, "build_type", None) in (None, ""):
        args.build_type = "Release"
    if getattr(args, "led", None) in (None, []) and args.cmd == "new":
        args.led = "PB5"
    if getattr(args, "button", None) in (None, []) and args.cmd == "new":
        args.button = "PD2"
    if getattr(args, "simavr_prefix", None) in (None, ""):
        args.simavr_prefix = os.environ.get("SIMAVR_PREFIX", "/usr/local")

    if getattr(args, "verbose", False):
        os.environ["MCU_VERBOSE"] = "1"

    try:
        return args.func(args, cfg) or 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":                # pragma: no cover
    sys.exit(main())
