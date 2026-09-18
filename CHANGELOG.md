# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

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
