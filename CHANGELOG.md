# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Fixed

- `mcu fuses` took the avrdude part from the CLI's `args.mcu` default instead of the
  project (`_avrdude(args, args)`): a non-ATmega328P project — an ATmega2560 or an
  ATmega4809 — was addressed as `-p m328p`, i.e. the wrong chip. The part now comes from
  the project, and the stub-avrdude tests no longer inherit `FAKE_*` variables from the
  caller's environment (which made them fail depending on the surrounding shell).

### Added

- **AVR8X support** (megaAVR 0-series: ATmega4808/4809/3208/3209/808/809/1608/1609;
  tinyAVR 0/1/2-series, 55 parts) — a different core from classic AVR8, not a rename:
  `PORT_t` registers, per-pin port interrupts, `USART0`, UPDI instead of ISP, and
  `fuse0…fuse8` instead of `lfuse`/`hfuse`/`efuse`.
- `mcu fuses` on an AVR8X part reads the whole 10-byte fuse block in one avrdude read
  (`fuses` @0x1280) and decodes the bytes by their documented names (WDTCFG, BODCFG,
  OSCCFG, TCD0CFG, SYSCFG0, SYSCFG1, APPEND, BOOTEND) plus the `OSCCFG`/`SYSCFG0` bit
  fields. Writes take named bytes: `--fuse SYSCFG0=0xF6`, `--fuse OSCCFG=0x7F`,
  `--fuse fuse8=0x02` (CODESIZE/BOOTSIZE accepted as aliases of fuse7/fuse8), and the
  block is read back and re-decoded afterwards. A `SYSCFG0.RSTPINCFG` change warns
  that PA0 becomes RESET and UPDI entry then needs the debugger's fuse override.
- AVR8X refusals instead of silent nonsense: `--lfuse/--hfuse/--efuse` are rejected with
  the byte each one became (clock → OSCCFG, system bits → SYSCFG0/SYSCFG1), `--dwen` is
  rejected as a classic debugWIRE concept, `--fuse` is rejected on classic parts, and a
  missing UPDI programmer is reported before avrdude ever runs.
- `mcu new --mcu atmega4809` (and any AVR8X part) now emits an AVR8X template with its own
  README: `PORTx.DIRSET/OUTTGL/PINnCTRL`, a `PORTx_PORT_vect` button ISR, `USART0` with
  the fractional baud register (`BAUD = 64·f_CPU/(16·baud)`, Microchip TB3216; 20 MHz →
  694, +0.06 %) and UPDI flash instructions. It compiles clean with `-Wall -Wextra`
  (verified against real avr-gcc for atmega4809 and attiny1616).
- AVR8X parts are refused by `sim`/`board`/`debug`/`trace` with the reason (simavr has no
  megaAVR 0 / tinyAVR core) and the bench workflow, instead of simavr's `unknown mcu`.
  `mcu flash` on an AVR8X part demands `--programmer …_updi` and rejects
  bootloader/ISP methods.
- `mcu build` on an AVR8X project now checks that the installed avr-gcc actually knows the
  part (one empty compile) and says so in words — "this avr-gcc has no atmega4809 device
  spec … needs avr-gcc ≥ 8, this one is 7.3.0" — instead of letting the build die with
  `device-specs/specs-atmega4809: No such file or directory`. Ubuntu 22.04's avr-gcc
  7.3.0 is exactly that case.
- `mcu fuses` — read `lfuse`/`hfuse`/`efuse` (`avrdude -U …:r:…:r`, so there is no
  avrdude text format to guess at) and decode hfuse; write explicit values
  (`--lfuse 0xFF --hfuse 0xD9 --efuse 0xFF`, avrdude's immediate `:m` format) and read
  them back afterwards. Fuses are no longer "not modelled".
- `mcu fuses --dwen {on,off}` — the debugWIRE switch, as a read-modify-write of hfuse
  bit 6 (DWEN): it reads the chip first, so only that bit moves; it is idempotent, and it
  refuses `off` when SPIEN is unprogrammed instead of writing a chip ISP can no longer
  reach. Enabling DWEN warns that ISP is taken over at the next power cycle.
- Programming a DWEN chip over ISP now works in one invocation: avrdude's
  `ISP activation failed, trying debugWIRE` / `restart avrdude without power-cycling`
  answer is recognised, warned about and the command is retried once — that retry is the
  documented sequence. `mcu flash` over ISP points at `mcu fuses --dwen off` when it
  fails instead.
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

### Changed

- The scaffolded `src/main.c` is much shorter and now marks the one block you are
  meant to replace: pin/UART/interrupt plumbing above, a `YOUR CODE HERE` region in
  `main()` holding the minimal demo (heartbeat, button press, serial echo) that
  `mcu sim`/`mcu board` need to show something out of the box. The old demo
  (`blink_enabled`/`button_events`, `tick <n>` counter, upper-casing RX echo), the
  no-op `__AVR_ATmega328P__` guard and `ctype.h` are gone, the two init helpers are
  folded into one `io_init()`, and the Cortex-M `main.c` carries the same marker. The
  AVR scaffold now builds to ~530 bytes instead of ~2100.

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
