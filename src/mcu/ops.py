"""Command implementations: doctor, new, build, flash, monitor, sim, board, debug, trace."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

from . import config as cfgmod
from . import harness
from . import scaffold
from .project import Project
from .util import (C_DIM, C_OFF, arm_newlib_ok, die, have, info, install_hint, need,
                   ok, parse_ms, parse_portpin, parse_label, pick_port, require, run,
                   serial_ports, simavr_caps, simavr_note, step, warn)


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
    run(cmd, dry=args.dry_run)
    if not args.dry_run:
        ok("flashed")
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


def cmd_sim(args, cfg):
    proj = project_of(args)
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
