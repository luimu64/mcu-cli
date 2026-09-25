"""Command implementations: doctor, new, build, flash, monitor, sim, board, debug, trace."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time

from . import config as cfgmod
from . import harness
from . import scaffold
from .project import Project
from .util import (C_DIM, C_OFF, arm_newlib_ok, die, have, info, install_hint,
                   is_avr8x, need, ok, parse_ms, parse_portpin, parse_label,
                   pick_port, require, run, serial_ports, simavr_caps, simavr_note,
                   step, warn)


# --------------------------------------------------------------------------
# shared
# --------------------------------------------------------------------------

def project_of(args) -> Project:
    return Project.find(getattr(args, "project", None))


def simavr_prefix(args, cfg) -> str:
    return (os.environ.get("SIMAVR_PREFIX")
            or getattr(args, "simavr_prefix", None)
            or cfg.get("simavr_prefix") or "/usr/local")


def firmware_of(proj: Project, args) -> str:
    fw = getattr(args, "firmware", None)
    if fw:
        return os.path.abspath(fw)
    if os.path.isfile(proj.elf):
        return proj.elf
    die("no firmware found — run `mcu build` first, or pass --firmware FILE")


def peripherals_of(args, cfg) -> harness.Peripherals:
    """--led/--button/--press/--rx, falling back to the config file defaults."""
    led_specs = list(getattr(args, "led", None) or cfg.get("led") or [])
    btn_specs = list(getattr(args, "button", None) or cfg.get("button") or [])
    press_specs = list(getattr(args, "press", None) or cfg.get("press") or [])
    rx_specs = list(getattr(args, "rx", None) or cfg.get("rx") or [])

    leds = []
    for spec in led_specs:
        port, bit = parse_portpin(spec)
        leds.append((port, bit, parse_label(spec, port, bit)))
    buttons = [parse_portpin(s) for s in btn_specs]

    presses = []
    for spec in press_specs:
        parts = str(spec).split(":")
        idx = 0
        if len(parts) == 3:
            idx = int(parts.pop(0))
        if len(parts) != 2:
            die(f"--press wants <at>:<hold> or <btn>:<at>:<hold>, got '{spec}'")
        if idx >= len(buttons):
            die(f"--press references button {idx}, but only {len(buttons)} defined")
        presses.append((idx, parse_ms(parts[0]), parse_ms(parts[1])))

    rx = []
    for spec in rx_specs:
        if ":" not in str(spec):
            die(f"--rx wants <at>:<text>, got '{spec}'")
        at, text = str(spec).split(":", 1)
        rx.append((parse_ms(at), text))

    return harness.Peripherals(leds, buttons, presses, rx)


# --------------------------------------------------------------------------
# doctor / list
# --------------------------------------------------------------------------

def cmd_doctor(args, cfg):
    step("host")
    info(f"  python      {sys_version()}")
    info(f"  platform    {os.uname().sysname if hasattr(os, 'uname') else os.name}")
    info(f"  config      {cfgmod.config_path()}"
         f"{'' if cfgmod.config_path().is_file() else ' (not present)'}")

    groups = [
        ("build", [("cmake", ["cmake", "--version"]),
                   ("ninja", ["ninja", "--version"]),
                   ("make", ["make", "--version"])]),
        ("AVR toolchain", [("avr-gcc", ["avr-gcc", "--version"]),
                           ("avr-objcopy", ["avr-objcopy", "--version"]),
                           ("avr-size", ["avr-size", "--version"]),
                           ("avrdude", ["avrdude", "-v"]),
                           ("avr-gdb", ["avr-gdb", "--version"])]),
        ("ARM toolchain", [("arm-none-eabi-gcc", ["arm-none-eabi-gcc", "--version"]),
                           ("arm-none-eabi-gdb", ["arm-none-eabi-gdb", "--version"]),
                           ("pyocd", ["pyocd", "--version"]),
                           ("probe-rs", ["probe-rs", "--version"]),
                           ("openocd", ["openocd", "--version"])]),
        ("simulation", [("simavr", ["simavr", "--list-cores"]),
                        ("qemu-system-avr", ["qemu-system-avr", "--version"])]),
        ("monitor", [("picocom", ["picocom", "-h"])]),
    ]
    missing = []
    for title, tools in groups:
        step(title)
        for name, cmd in tools:
            path = have(name)
            if not path:
                missing.append(name)
                info(f"  {C_DIM}{name:22s} -{C_OFF}")
                continue
            rc, out = run(cmd, capture=True, check=False)
            if name == "simavr":
                # --list-cores prints the list and still exits 1; no --version flag
                cores = [l for l in (out or "").splitlines() if l.strip()]
                info(f"  {name:22s} ok ({max(len(cores) - 1, 0)} cores, {path})")
                info(f"  {'simavr flags':22s} {simavr_note(simavr_caps())}")
                continue
            first = ""
            for line in (out or "").splitlines():
                line = line.strip()
                if line and not line.startswith("Usage") and "cannot" not in line:
                    first = line
                    break
            m = re.search(r"(\d+\.\d+(\.\d+)?)", first)
            info(f"  {name:22s} {m.group(1) if m else first[:28]}")

    if have("arm-none-eabi-gcc") and not arm_newlib_ok():
        warn("arm-none-eabi-gcc has no bare-metal C library (newlib): ARM links "
             "will fail with 'cannot find -lc'.")
        info(f"     install: {install_hint('arm-none-eabi-gcc')}")

    step("devices")
    ports = serial_ports()
    if ports:
        for p in ports:
            info(f"  serial               {p}")
    else:
        info(f"  {C_DIM}serial               none attached{C_OFF}")
    if have("pyocd"):
        rc, out = run(["pyocd", "list"], capture=True, check=False)
        found = False
        for line in (out or "").splitlines():
            if re.search(r"(?i)(cmsis|daplink|st-link|j-link|probe|serial)", line):
                info(f"  probe                {line.strip()}")
                found = True
        if not found:
            info(f"  {C_DIM}probe                none attached{C_OFF}")

    if missing:
        step("missing tools")
        for name in missing:
            info(f"  {name:22s} {install_hint(name)}")
    return 0


def sys_version() -> str:
    import sys
    return sys.version.split()[0]


def cmd_list(args, cfg):
    if args.what == "cores":
        need("simavr", why="it enumerates the emulated MCUs")
        rc, out = run(["simavr", "--list-cores"], capture=True, check=False)
        for line in out.splitlines():
            line = line.strip()
            if line and not line.lower().startswith("supported"):
                info(line)
        return 0
    if args.what == "parts":
        prefix = simavr_prefix(args, cfg)
        root = os.path.join(prefix, "include", "simavr", "parts")
        if not os.path.isdir(root):
            die(f"no simavr parts installed at {root} "
                f"(set SIMAVR_PREFIX if simavr lives elsewhere)")
        for f in sorted(os.listdir(root)):
            if f.endswith(".h"):
                info(f[:-2])
        return 0
    die(f"unknown list target '{args.what}' (cores|parts)")


# --------------------------------------------------------------------------
# new / build / clean / size
# --------------------------------------------------------------------------

def cmd_new(args, cfg):
    return scaffold.create(
        args.path, name=args.name, arch=args.arch, mcu=args.mcu, freq=args.freq,
        led=args.led, button=args.button, baud=args.baud, cpu=args.cpu,
        float_abi=args.float_abi, chip=args.chip, flash=args.flash, ram=args.ram,
        flash_origin=args.flash_origin, ram_origin=args.ram_origin, force=args.force)


def do_build(proj: Project, args) -> int:
    require("cmake", args.dry_run)
    require("ninja", args.dry_run)
    require("avr-gcc" if proj.arch == "avr" else "arm-none-eabi-gcc", args.dry_run)
    if (proj.arch == "arm" and not args.dry_run
            and have("arm-none-eabi-gcc") and not arm_newlib_ok()):
        # better here than as a bare "ld: cannot find -lc" halfway through the link
        warn("arm-none-eabi-gcc cannot find its bare-metal C library (newlib); "
             "the link would fail with 'cannot find -lc'.")
        info(f"     install: {install_hint('arm-none-eabi-gcc')}")
    if not proj.configured() or args.reconfigure:
        step(f"configure ({proj.arch}, mcu={proj.mcu}, {proj.freq} Hz)")
        run(proj.configure_cmd(args.build_type), dry=args.dry_run, cwd=proj.dir)
    step("build")
    run(["cmake", "--build", "build"], dry=args.dry_run, cwd=proj.dir)
    if not args.dry_run:
        ok(os.path.relpath(proj.elf, proj.dir))
    return 0


def cmd_build(args, cfg):
    return do_build(project_of(args), args)


def cmd_clean(args, cfg):
    proj = project_of(args)
    for rel in ("build", os.path.join("sim", "generated")):
        p = os.path.join(proj.dir, rel)
        if os.path.isdir(p):
            step(f"remove {p}")
            if not args.dry_run:
                shutil.rmtree(p)
    ok("clean")
    return 0


def cmd_size(args, cfg):
    proj = project_of(args)
    if not os.path.isfile(proj.elf) and not args.dry_run:
        die("no ELF yet — run `mcu build`")
    require("avr-size" if proj.arch == "avr" else "arm-none-eabi-size", args.dry_run)
    run(proj.size_cmd(), dry=args.dry_run)
    if proj.arch == "arm":
        run(["arm-none-eabi-size", proj.elf], dry=args.dry_run)
    return 0


# --------------------------------------------------------------------------
# flash / monitor
# --------------------------------------------------------------------------

def cmd_flash(args, cfg):
    proj = project_of(args)
    part = args.part
    if not part:
        part = "m328p" if proj.mcu == "atmega328p" else proj.mcu

    if proj.arch == "arm":
        if args.programmer or args.bitclock:
            die("--programmer/--bitclock are AVR ISP options — ARM targets flash "
                "through pyocd over CMSIS-DAP, which is already the probe")
        require("pyocd", args.dry_run, why="it talks to CMSIS-DAP probes")
        step(f"pyocd flash {os.path.basename(proj.elf)}")
        run(["pyocd", "flash", proj.elf], dry=args.dry_run)
        if not args.dry_run:
            ok("flashed")
        return 0

    if is_avr8x(proj.mcu):
        if args.method in ("auto", "bootloader"):
            die(f"{proj.mcu} is AVR8X: it has no ISP and no serial bootloader — "
                f"it is programmed over UPDI.\n"
                f"     mcu flash --method icsp --programmer atmelice_updi")
        if not args.programmer:
            die(f"{proj.mcu} is AVR8X: pass the UPDI programmer explicitly "
                f"(there is no ISP to fall back on):\n"
                f"     mcu flash --method icsp --programmer atmelice_updi")

    require("avrdude", args.dry_run)
    hexf = args.file or proj.hex
    if not os.path.isfile(hexf) and not args.dry_run:
        die(f"{hexf} not found — run `mcu build` first")

    method = args.method
    if method == "auto":
        method = "bootloader"

    if method == "bootloader":
        if args.programmer or args.bitclock:
            die("--programmer/--bitclock need a hardware programmer — use "
                "--method icsp (a USB bootloader has no probe and no ISP clock)")
        port = args.port or cfg.get("port") or pick_port(None, dry=args.dry_run)
        cmd = ["avrdude", "-c", "arduino", "-b", str(args.baud),
               "-p", part, "-P", port, "-D", "-U", f"flash:w:{hexf}:i"]
        if not args.dry_run and not os.access(port, os.R_OK | os.W_OK):
            die(f"no permission on {port} — add your user to the group owning it "
                f"(uucp/dialout on most distros)")
    elif method in ("usbasp", "icsp"):
        # One avrdude -c id, defaulting to the old hard-coded usbasp. This is
        # what makes a bare chip reachable: a probe like the Atmel-ICE is just
        # another avrdude programmer id (`atmelice_isp` for SPI/ISP,
        # `atmelice_dw` for a debugWIRE session).
        prog = args.programmer or "usbasp"
        method = f"icsp ({prog})"
        cmd = ["avrdude", "-c", prog, "-p", part]
        if args.bitclock:
            # ISP SCK must stay under a quarter of the target clock; a
            # factory-fresh ATmega328P runs at 1MHz, so the default is too fast.
            cmd += ["-B", f"{args.bitclock:g}"]
        if args.port:
            cmd += ["-P", args.port]
        cmd += ["-U", f"flash:w:{hexf}:i"]
    else:
        die(f"unknown flash method '{method}'")

    step(f"flash via {method}")
    rc, _ = run(cmd, dry=args.dry_run, check=False)
    if rc:
        if method.startswith("icsp"):
            warn("ISP failed — if this chip has DWEN programmed, debugWIRE owns "
                 "RESET and ISP cannot be entered: `mcu fuses --dwen off` prepares "
                 "the target and retries, and so does running avrdude again "
                 "without power-cycling")
        die(f"avrdude failed ({rc})")
    if not args.dry_run:
        ok("flashed")
    return 0


# --------------------------------------------------------------------------
# fuses (debugWIRE / DWEN lives here)
# --------------------------------------------------------------------------

# Classic AVR8 (mega/tiny) hfuse bit map. Programmed = 0, unprogrammed = 1;
# other families move these bits around, hence the part note in the output.
HFUSE_BITS = (("RSTDISBL", 7), ("DWEN", 6), ("SPIEN", 5), ("WDTON", 4),
              ("EESAVE", 3), ("BOOTSZ1", 2), ("BOOTSZ0", 1), ("BOOTRST", 0))
DWEN_BIT = 6
SPIEN_BIT = 5
FUSES = ("lfuse", "hfuse", "efuse")

# avrdude says this when it had to reset a debugWIRE-locked target to get at ISP
# at all; the documented follow-up is to run the same command again (the target
# stays prepared until it is power-cycled).
_DW_RETRY_MARKERS = ("trying debugWIRE", "power-cycling the target")


def _avrdude(proj, args) -> list:
    """Base avrdude argv: programmer, part, ISP clock, port."""
    prog = args.programmer or "usbasp"
    part = args.part or ("m328p" if proj.mcu == "atmega328p" else proj.mcu)
    cmd = ["avrdude", "-c", prog, "-p", part]
    if args.bitclock:
        cmd += ["-B", f"{args.bitclock:g}"]
    if args.port:
        cmd += ["-P", args.port]
    return cmd


def _avrdude_retry(cmd, dry, what):
    """Run avrdude, retrying once after it prepared a debugWIRE target.

    A chip with DWEN programmed answers no ISP until the probe interrupts the
    debugWIRE session; avrdude does that itself and then asks to be run again
    without power-cycling. Doing it here keeps the FW/SW switch-over a one-liner.
    """
    rc, out = run(cmd, dry=dry, capture=not dry, check=False)
    if not dry and rc and any(m in out for m in _DW_RETRY_MARKERS):
        warn("target is in debugWIRE mode: avrdude prepared it for ISP, retrying")
        rc, out = run(cmd, capture=True, check=False)
    if not dry and rc and os.environ.get("MCU_VERBOSE"):
        info(out.rstrip())
    return rc, out


def _fuse_value(text, name) -> int:
    try:
        value = int(str(text), 0)
    except ValueError:
        die(f"cannot parse {name} '{text}' (use 0xFF or 255)")
    if not 0 <= value <= 0xFF:
        die(f"{name} is one byte: 0x00-0xFF")
    return value


def _read_fuse(base, mem, dry):
    """Read one fuse byte back from the chip.

    avrdude's raw format (`r`) puts exactly that byte in the file, so there is no
    text format (0xff vs FF vs 255) to guess at.
    """
    if dry:
        run(base + ["-U", f"{mem}:r:<tmpfile>:r"], dry=True)
        return None
    with tempfile.TemporaryDirectory(prefix="mcu-fuse-") as td:
        path = os.path.join(td, mem)
        rc, out = _avrdude_retry(base + ["-U", f"{mem}:r:{path}:r"], dry, mem)
        if rc:
            die(f"could not read {mem} (avrdude exit {rc})"
                + (f"\n{out.strip()}" if out.strip() else ""))
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            data = b""
        if not data:
            die(f"avrdude reported success but wrote no {mem} data — check the "
                f"programmer id, the wiring and the ISP clock (-B)")
        return data[0]


def _hfuse_report(value) -> list:
    bits = " ".join(f"{n}={value >> b & 1}" for n, b in HFUSE_BITS)
    dwen = "unprogrammed (debugWIRE off)" if value >> DWEN_BIT & 1 \
        else "PROGRAMMED (debugWIRE on)"
    spien = "programmed (ISP usable)" if not value >> SPIEN_BIT & 1 \
        else "unprogrammed (ISP disabled)"
    return [f"     hfuse bits, classic AVR order: {bits}",
            f"     DWEN {dwen}; SPIEN {spien}"]


# --------------------------------------------------------------------------
# AVR8X fuses: one 10-byte block at 0x1280 (avrdude memory "fuses"), no
# lfuse/hfuse/efuse, and the part is reachable over UPDI only.
# --------------------------------------------------------------------------

AVR8X_FUSE_BLOCK = 0x1280
AVR8X_FUSES = ("WDTCFG", "BODCFG", "OSCCFG", "FUSE3", "TCD0CFG", "SYSCFG0",
               "SYSCFG1", "APPEND", "BOOTEND", "FUSE9")
AVR8X_ALIASES = {"CODESIZE": 7, "BOOTSIZE": 8}     # same bytes, other datasheet name
AVR8X_CLASSIC_NAMES = {                            # what a classic user reaches for
    "lfuse": "OSCCFG (fuse2) holds the clock select",
    "hfuse": "SYSCFG0/SYSCFG1 (fuse5/fuse6) hold the system bits",
    "efuse": "BODCFG/APPEND/BOOTEND cover what efuse did",
}
# megaAVR 0-series bit names for the two bytes that actually bite
AVR8X_BIT_FIELDS = {
    "OSCCFG": (("FREQSEL", 0, 0x03), ("OSCLOCK", 7, 0x80)),
    "SYSCFG0": (("EESAVE", 0, 0x01), ("RSTPINCFG", 3, 0x08), ("CRCSRC", 6, 0xC0)),
}
AVR8X_UPDI_PROGRAMMERS = ("atmelice_updi", "serialupdi", "jtag2updi", "pkobn_updi",
                          "pickit4_updi", "pickit5_updi")


def _avr8x_fuse_index(name) -> int:
    key = str(name).strip().upper()
    if key in AVR8X_ALIASES:
        return AVR8X_ALIASES[key]
    m = re.fullmatch(r"FUSE([0-9])", key)
    if m:
        return int(m.group(1))
    if key in AVR8X_FUSES:
        return AVR8X_FUSES.index(key)
    die(f"unknown AVR8X fuse '{name}' (use fuse0..fuse9 or one of "
        f"{', '.join(AVR8X_FUSES)}; CODESIZE/BOOTSIZE are fuse7/fuse8)")


def _read_fuse_block(base, dry):
    """The whole AVR8X fuse block in one read: avrdude's `fuses` memory."""
    if dry:
        run(base + ["-U", "fuses:r:<tmpfile>:r"], dry=True)
        return None
    with tempfile.TemporaryDirectory(prefix="mcu-fuse-") as td:
        path = os.path.join(td, "fuses")
        rc, out = _avrdude_retry(base + ["-U", f"fuses:r:{path}:r"], dry, "fuses")
        if rc:
            die(f"could not read the fuse block (avrdude exit {rc})"
                + (f"\n{out.strip()}" if out.strip() else ""))
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            data = b""
        if not data:
            die("avrdude reported success but wrote no fuse data — check the "
                "programmer id (`--programmer atmelice_updi` for UPDI), the wiring "
                "and the target's supply")
        return data


def _avr8x_report(data) -> list:
    shown = " ".join(f"{b:02X}" for b in data)
    lines = [f"fuses@{AVR8X_FUSE_BLOCK:#06x} = {shown}"]
    names = []
    for i, b in enumerate(data):
        name = AVR8X_FUSES[i] if i < len(AVR8X_FUSES) else f"FUSE{i}"
        names.append(f"{i} {name}=0x{b:02X}")
    for chunk in (names[:5], names[5:10], names[10:]):
        if chunk:
            lines.append("     " + "  ".join(chunk))
    for i, name in enumerate(AVR8X_FUSES):
        if i in (2, 5) and i < len(data):            # OSCCFG, SYSCFG0
            bits = []
            for field, pos, mask in AVR8X_BIT_FIELDS[name]:
                value = (data[i] & mask) >> pos
                text = f"{field}=(0x{data[i]:02X} & {mask:#04x}) >> {pos} = {value}"
                if field == "RSTPINCFG":             # header: GPIO_gc / RST_gc
                    text += (" (PA0 is a plain I/O pin)" if value == 0
                             else " (PA0 drives RESET — UPDI entry then needs the "
                                  "debugger's fuse override)")
                bits.append(text)
            lines.append(f"     {name} (megaAVR 0-series names): " + "; ".join(bits))
    lines.append("     bit names above are megaAVR 0-series; tinyAVR 2-series move "
                 "them (e.g. SYSCFG0.UPDIPINCFG) — check that part's datasheet")
    return lines


def _fuses_avr8x(proj, args):
    if not args.programmer:
        die(f"{proj.mcu} is an AVR8X part: it has no ISP, it is programmed over "
            f"UPDI.\n     pass a UPDI programmer: "
            + ", ".join(f"-c {p}" for p in AVR8X_UPDI_PROGRAMMERS[:3]))
    base = _avrdude(proj, args)

    for name in FUSES:                               # --lfuse / --hfuse / --efuse
        if getattr(args, name, None) is not None:
            die(f"AVR8X has no {name} (that is the classic AVR8 naming): "
                f"{AVR8X_CLASSIC_NAMES[name]}.\n     write the byte instead: "
                f"mcu fuses --fuse {name.replace('lfuse', 'OSCCFG').replace('hfuse', 'SYSCFG0').replace('efuse', 'BODCFG')}=0x..")
    if args.dwen:
        die("--dwen is a classic AVR8 fuse (debugWIRE). AVR8X debugs over UPDI, "
            "which needs no fuse.\n     the SYSCFG0 equivalent is RSTPINCFG "
            "(bit 3): it hands PA0 to RESET/the application, and a debugger then "
            "needs the 'UPDI enable with fuse override' sequence to get back in.")

    wanted = {}
    for spec in args.fuse or []:
        name, _, text = str(spec).partition("=")
        if not _:
            die(f"--fuse wants NAME=HEX, got '{spec}' (e.g. --fuse SYSCFG0=0xF6)")
        index = _avr8x_fuse_index(name)
        wanted[index] = _fuse_value(text, name)

    if not wanted:                                   # read
        step("read fuses")
        if args.dry_run:
            _read_fuse_block(base, True)
            return 0
        data = _read_fuse_block(base, False)
        for line in _avr8x_report(data):
            info(line)
        return 0

    before = None
    if not args.dry_run:
        before = _read_fuse_block(base, False)
        if 5 in wanted and before and 5 < len(before) and \
                (before[5] & 0x08) != (wanted[5] & 0x08):
            warn("SYSCFG0.RSTPINCFG "
                 f"{(before[5] & 0x08) >> 3} -> {(wanted[5] & 0x08) >> 3}: "
                 + ("PA0 becomes RESET for the application, so UPDI entry then "
                    "needs the debugger's 'UPDI enable with fuse override' "
                    "sequence" if (wanted[5] & 0x08) else
                    "PA0 stops driving RESET (GPIO mode)"))
        for i in sorted(wanted):
            current = before[i] if i < len(before) else None
            if current is not None:
                info(f"{AVR8X_FUSES[i]} (fuse{i}) 0x{current:02X} -> "
                     f"0x{wanted[i]:02X}")

    cmds = [f"fuse{i}:w:0x{v:02X}:m" for i, v in sorted(wanted.items())]
    step("write " + ", ".join(f"fuse{i}" for i in sorted(wanted)))
    rc, out = _avrdude_retry(base + [x for c in cmds for x in ("-U", c)],
                             args.dry_run, "fuses")
    if not args.dry_run and rc:
        die(f"avrdude failed ({rc})"
            + (f"\n{out.strip()}" if out.strip() else ""))
    if not args.dry_run:
        ok("wrote " + ", ".join(f"{AVR8X_FUSES[i]}=0x{wanted[i]:02X}"
                                for i in sorted(wanted)))
        data = _read_fuse_block(base, False)
        for line in _avr8x_report(data):
            info(line)
    return 0


def cmd_fuses(args, cfg):
    proj = project_of(args)
    if proj.arch == "arm":
        die("a Cortex-M part has no fuse bytes — fuses are an AVR concept")
    require("avrdude", args.dry_run)
    if is_avr8x(proj.mcu):
        return _fuses_avr8x(proj, args)

    if args.fuse:
        die("--fuse NAME=HEX is the AVR8X spelling; classic AVR8 parts take "
            "--lfuse/--hfuse/--efuse")
    base = _avrdude(proj, args)

    wanted = {}
    for name in FUSES:
        text = getattr(args, name, None)
        if text is not None:
            wanted[name] = _fuse_value(text, name)

    if args.dwen and "hfuse" in wanted:
        die("--dwen derives hfuse from the chip's current value — don't pass "
            "--hfuse as well")

    if not wanted and not args.dwen:                      # read
        step("read fuses")
        if args.dry_run:
            for m in FUSES:
                _read_fuse(base, m, True)
            return 0
        values = {m: _read_fuse(base, m, False) for m in FUSES}
        info(f"lfuse=0x{values['lfuse']:02X} hfuse=0x{values['hfuse']:02X} "
             f"efuse=0x{values['efuse']:02X}")
        for line in _hfuse_report(values["hfuse"]):
            info(line)
        return 0

    if args.dwen:                                         # read-modify-write
        step(f"read hfuse to {'set' if args.dwen == 'on' else 'clear'} DWEN")
        if args.dry_run:
            _read_fuse(base, "hfuse", True)
            info(f"     the value written follows from that read: DWEN is bit "
                 f"{DWEN_BIT}, 0 = programmed = debugWIRE enabled")
            return 0
        current = _read_fuse(base, "hfuse", False)
        if args.dwen == "on":
            new = current & ~(1 << DWEN_BIT)
        else:
            if current >> SPIEN_BIT & 1:
                die("SPIEN is unprogrammed on this part, so ISP cannot reach it "
                    "even without DWEN.\n     disable debugWIRE from inside a "
                    "debugWIRE session instead (avrdude -c atmelice_dw -p <part> -t, "
                    "then `monitor debugwire disable`), or use a high-voltage "
                    "programmer (STK500/Dragon — the Atmel-ICE has no HVPP/PP)")
            new = current | (1 << DWEN_BIT)
        if new == current:
            ok(f"hfuse=0x{current:02X} already has DWEN "
               f"{'programmed' if args.dwen == 'on' else 'unprogrammed'} — "
               f"nothing written")
        else:
            wanted["hfuse"] = new
            info(f"hfuse 0x{current:02X} -> 0x{new:02X}")
            if args.dwen == "on":
                warn("DWEN programmed: ISP is taken over by debugWIRE as soon as "
                     "the target is power-cycled")
                warn("flash over ISP first — afterwards flash/EEPROM stay "
                     "programmable over debugWIRE, but fuses do not")

    cmds = [f"{m}:w:0x{v:02X}:m" for m, v in wanted.items() if wanted[m] is not None]
    if not cmds:
        return 0
    step("write " + ", ".join(m for m in wanted))
    rc, out = _avrdude_retry(base + [x for c in cmds for x in ("-U", c)],
                             args.dry_run, "fuses")
    if not args.dry_run and rc:
        die(f"avrdude failed ({rc})"
            + (f"\n{out.strip()}" if out.strip() else ""))
    if not args.dry_run:
        ok("wrote " + ", ".join(f"{m}=0x{wanted[m]:02X}" for m in wanted))
        values = {m: _read_fuse(base, m, False) for m in FUSES}
        info(f"read back: lfuse=0x{values['lfuse']:02X} "
             f"hfuse=0x{values['hfuse']:02X} efuse=0x{values['efuse']:02X}")
        if args.dwen == "on":
            info("     next: power-cycle the target, then debug over debugWIRE "
                 "(-c atmelice_dw, or dw-gdbserver on a serial probe)")
        elif args.dwen == "off":
            info("     next: power-cycle the target — ISP works again")
    return 0


def cmd_monitor(args, cfg):
    port = args.port or cfg.get("port") or pick_port(None, dry=args.dry_run)
    rc, _ = run(["picocom", "-b", str(args.baud), port],
                dry=args.dry_run, check=False)
    if rc and not args.dry_run and not have("picocom"):
        die(f"picocom not found.\n     install: {install_hint('picocom')}")
    return rc


# --------------------------------------------------------------------------
# sim / board / debug / trace
# --------------------------------------------------------------------------

def _sim_base(proj: Project, args) -> list:
    return ["simavr", "-m", args.mcu or proj.mcu, "-f", str(args.freq or proj.freq)]


def no_simulator(proj: Project):
    """AVR8X (megaAVR 0 / tinyAVR) is not emulated: simavr has classic AVR8 cores
    only, so sim/board/debug/trace have nothing to run there."""
    if proj.arch == "avr" and is_avr8x(proj.mcu):
        die(f"simavr has no {proj.mcu} core: AVR8X parts are not emulated, so "
            f"sim/board/debug/trace do not apply.\n"
            f"     this part is bench-only: mcu flash --method icsp --programmer "
            f"atmelice_updi && mcu monitor")


def cmd_sim(args, cfg):
    proj = project_of(args)
    no_simulator(proj)
    fw = firmware_of(proj, args)
    require("simavr", args.dry_run)
    caps = simavr_caps()

    cmd = _sim_base(proj, args)
    if args.gdb is not None:
        if "gdb_port" in caps:
            cmd += ["-g", str(args.gdb)]
        elif args.gdb == 1234:
            cmd += ["-g"]
            warn("this simavr build takes a bare -g: gdb stub on 1234")
        else:
            die("this simavr build has no `-g <port>` (its gdb stub is fixed on "
                "1234)\n     use --gdb 1234, or build simavr from source")

    sigs = args.signal or []
    if sigs and "signal" not in caps:
        warn("this simavr build has no `-at`: signal traces ignored "
             "(simavr 1.6 has no VCD signal selection)")
        sigs = []

    out_path = None
    if args.trace:
        if "output" in caps:
            cmd += ["-o", args.trace]
        else:
            # 1.6 has no -o; it writes the VCD on stdout.
            out_path = args.trace
    for sig in sigs:
        cmd += ["-at", sig]
    cmd.append(fw)
    if args.seconds:
        cmd = ["timeout", str(args.seconds), *cmd]

    step(f"simavr {proj.mcu} @ {proj.freq} Hz")
    rc, _ = run(cmd, dry=args.dry_run, check=False, stdout_path=out_path)
    if rc == 124:
        info(f"{C_DIM}     (stopped after {args.seconds}s of simulated time){C_OFF}")
    return 0


def cmd_board(args, cfg):
    proj = project_of(args)
    no_simulator(proj)
    fw = firmware_of(proj, args)
    periph = peripherals_of(args, cfg)
    binary = harness.build(proj, periph,
                           prefix=simavr_prefix(args, cfg),
                           cc=args.cc or cfg.get("cc") or "cc",
                           uart=not args.no_uart, keys=args.keys,
                           dry=args.dry_run)

    cmd = [binary, fw]
    seconds = args.seconds if args.seconds is not None else cfg.get("seconds")
    if seconds:
        cmd += ["--seconds", str(seconds)]

    step("board: simavr + peripherals")
    run(cmd, dry=args.dry_run, check=False)
    return 0


def cmd_debug(args, cfg):
    proj = project_of(args)
    if args.hw:
        return _debug_hw(proj, args)
    if proj.arch != "avr":
        die("simulated debug is AVR-only (simavr + avr-gdb); use --hw for a probe")
    no_simulator(proj)

    fw = firmware_of(proj, args)
    caps = simavr_caps()
    port = args.gdb_port
    if "gdb_port" not in caps:
        # simavr 1.6 only takes a bare -g and always listens on 1234.
        if port != 1234:
            die("this simavr build has no `-g <port>` (its gdb stub is fixed on "
                "1234)\n     drop --gdb-port, or build simavr from source to get "
                "the port argument")
        warn("this simavr build takes a bare -g: gdb stub on 1234")

    def sim_cmd():
        c = ["simavr", "-m", proj.mcu, "-f", str(proj.freq)]
        c += ["-g", str(port)] if "gdb_port" in caps else ["-g"]
        return c + [fw]

    if args.dry_run:
        info("   $ " + " ".join(sim_cmd()))
        info(f"   $ avr-gdb {fw} -ex 'target remote :{port}'")
        return 0
    need("simavr")
    need("avr-gdb")
    sim = subprocess.Popen(sim_cmd(),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # Never probe the gdb port with a TCP connect: simavr's stub accepts a
        # single connection, so the probe steals gdb's slot and the real
        # "target remote" then blocks forever.
        for _ in range(20):
            if sim.poll() is not None:
                die("simavr gdbserver exited immediately "
                    "(is the port already in use?)")
            time.sleep(0.05)

        cmd = ["avr-gdb", "-q", fw,
               "-ex", "set confirm off", "-ex", "set pagination off",
               "-ex", f"target remote :{port}"]
        for e in (args.exe or []):
            cmd += ["-ex", e]
        if args.batch:
            cmd = ["timeout", str(args.timeout), *cmd, "-ex", "detach", "-ex", "quit"]
        else:
            info(f"     {C_DIM}tips: break main | continue | bt | "
                 f"x/1xb 0x800025 (PORTB, data space = 0x800000 + offset){C_OFF}")
        return run(cmd, check=False)[0]
    finally:
        sim.terminate()
        try:
            sim.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sim.kill()


def _debug_hw(proj: Project, args):
    need("pyocd", hint="pipx install pyocd")
    need("arm-none-eabi-gdb")
    if args.dry_run:
        info(f"   $ pyocd gdbserver --port {args.gdb_port} --persist")
        info(f"   $ arm-none-eabi-gdb {proj.elf} -ex 'target remote :{args.gdb_port}'")
        return 0
    if not args.batch:
        info("     start `pyocd gdbserver --port %d --persist` in another shell"
             % args.gdb_port)
    cmd = ["arm-none-eabi-gdb", "-q", proj.elf,
           "-ex", "set confirm off", "-ex", "set pagination off",
           "-ex", f"target remote :{args.gdb_port}"]
    for e in (args.exe or []):
        cmd += ["-ex", e]
    if args.batch:
        cmd = ["timeout", str(args.timeout), *cmd, "-ex", "detach", "-ex", "quit"]
    return run(cmd, check=False)[0]


DEFAULT_TRACES = ["PORTB=sram8@0x25", "PORTD=sram8@0x2B", "SECONDS=sram16@0x100"]


def cmd_trace(args, cfg):
    proj = project_of(args)
    no_simulator(proj)
    fw = firmware_of(proj, args)
    require("simavr", args.dry_run)
    caps = simavr_caps()
    out = args.output or os.path.join(proj.dir, "trace.vcd")
    sigs = args.signal or DEFAULT_TRACES

    if "signal" not in caps:
        die("this simavr build has no `-at <signal>`, so it cannot select what to "
            "trace\n     (Debian/Ubuntu ship simavr 1.6 without it). Either build "
            "simavr from source\n     (https://github.com/buserror/simavr), or "
            "read the SFRs with `mcu debug`\n     at a breakpoint: x/1xb "
            "0x800025 = PORTB")

    cmd = _sim_base(proj, args)
    out_path = None
    if "output" in caps:
        cmd += ["-o", out]
    else:
        out_path = out                       # 1.6-style build: VCD arrives on stdout
        warn(f"this simavr build has no -o: writing the VCD to {out} via stdout")
    for s in sigs:
        cmd += ["-at", s]
    cmd.append(fw)
    if args.seconds:
        cmd = ["timeout", str(args.seconds), *cmd]

    step(f"trace -> {out}")
    for s in sigs:
        info(f"     {C_DIM}{s}{C_OFF}")
    run(cmd, dry=args.dry_run, check=False, stdout_path=out_path)

    if not args.dry_run and os.path.isfile(out):
        with open(out) as fh:
            body = fh.read()
        changes = sum(1 for l in body.splitlines()
                      if l and not l.startswith("$") and not l.startswith("#"))
        stamps = re.findall(r"^#(\d+)$", body, re.M)
        ok(f"{os.path.getsize(out)} bytes, {changes} change(s)")
        if stamps:
            span = (int(stamps[-1]) - int(stamps[0])) / 1e9
            info(f"     simulated span {span:.2f} s")
        info(f"     {C_DIM}sram traces record changes, not values — pair with a "
             f"gdb read at a breakpoint for values{C_OFF}")
    return 0
