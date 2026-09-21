# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added

- `mcu flash --programmer ID` picks the avrdude programmer for `--method icsp` instead
  of the hard-coded `usbasp`, so an Atmel-ICE (`atmelice_isp` for SPI/ISP,
  `atmelice_dw` for a debugWIRE session), a JTAGICE3 (`jtag3isp`), an AVR Dragon or any
  other avrdude-known probe works without a special case. Default stays `usbasp`.
- `mcu flash -B/--bitclock US` passes avrdude's ISP clock period. Needed for a
  factory-fresh part: SCK must stay under a quarter of the target clock and a new
  ATmega328P runs at 1 MHz, so the default is too fast.
- `mcu flash --port` also reaches the programmer path as avrdude `-P` when given
  explicitly (the bootloader autodetect still does not leak into it).
- `--programmer`/`-B` are rejected for the bootloader method and on ARM projects
  instead of being silently ignored.

### Fixed

- `mcu debug` / `mcu sim --gdb` failed on simavr builds without the `-g <port>` form
  (Debian/Ubuntu ship 1.6, whose stub is fixed on 1234): the port number was read as
  the firmware name and the simulator exited with "gdbserver exited immediately". The
  optional flags are now probed behaviourally (`simavr_caps`), the bare `-g` is used
  when that is all the build supports, and asking for another port says so plainly
  instead of failing.
- `mcu trace` / `mcu sim --trace` no longer hand `-o`/`-at` to a simavr that has never
  heard of them (which made simavr try to load the `.vcd` as firmware): unsupported
  signal traces are refused with an actionable hint, and the VCD is written through
  stdout when `-o` is missing. `MCU_SIMAVR_FLAGS` overrides the probe.
- `mcu doctor` reports which of `-g <port>`/`-at`/`-o` the installed simavr accepts.
- `run()` can redirect a command's stdout to a file (no shell), used for VCDs.

## [1.0.0] — 2026-09-18

First release.

### Added

- `mcu new` — scaffolds an AVR (avr-libc) or Cortex-M project: CMakeLists, toolchain
  file, sources, `.gitignore`, README; ARM adds a linker script, a C startup file and
  `.zed/debug.json`.
- `mcu build` / `clean` / `size` — CMake + Ninja builds, ELF/HEX/BIN plus a memory report.
- `mcu flash` — `avrdude` over the USB bootloader or ICSP/`usbasp`; `pyocd` for Cortex-M.
- `mcu monitor` — `picocom` on the autodetected serial port.
- `mcu sim` — run firmware under simavr.
- `mcu board` — generates, compiles and runs a simavr **board harness** with LEDs,
  buttons and scripted/injected serial traffic (the headless equivalent of a
  simulator's on-screen peripherals).
- `mcu debug` — source-level debugging (`simavr -g` + `avr-gdb`), or `--hw` for a real
  ARM probe through `pyocd`.
- `mcu trace` — VCD signal traces from the simulation, summarised on exit.
- `mcu doctor` / `list cores|parts` — toolchain, device and capability inventory.
- Optional `~/.config/mcu/config.toml` for defaults; every CLI flag overrides it.
- Test suite (`python -m unittest discover -s tests`) with parser, project-detection,
  scaffolding, harness-generation and end-to-end build tests; integration tests skip
  themselves when a toolchain is absent.
