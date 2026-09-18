# mcu — one CLI for the embedded workflow

[![ci](https://github.com/luimu64/mcu-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/luimu64/mcu-cli/actions/workflows/ci.yml)

Scaffold, build, flash, monitor, **simulate with LEDs and buttons**, debug and trace —
AVR and Cortex-M, from one command, without a vendor IDE.

```
$ mcu board --led D13 --button D2 --press 1.5s:150ms --rx 1.2s:abc --seconds 8
board: build/blinky.elf (atmega328p @ 16000000 Hz)
  leds:1  buttons:1  uart:on
  --------------------------------------------------------------
[led         9.08 ms] D13   -> ON   (PORTB=0x20)
tick 0
[led       510.58 ms] D13   -> off  (PORTB=0x00)
[uart_rx  1200.00 ms] inject "abc"
[button   1500.00 ms] press PD2 (hold 150 ms)
button: heartbeat paused
[led      1516.63 ms] D13   -> off  (PORTB=0x00)
A
B
C
[button   3500.00 ms] press PD2 (hold 150 ms)
button: heartbeat resumed
```

## Why

A modern toolchain replaces a vendor IDE piece by piece — `avr-gcc`/`arm-none-eabi-gcc`
for builds, CMake+Ninja for the project, `avrdude`/`pyocd` for flashing, `simavr` +
`avr-gdb` for debugging — but that is six tools with six sets of flags, and the
simulator's on-screen peripherals (an LED on a pin, a button you click) have no
obvious equivalent. `mcu` is the missing glue:

- one command per step, with sane defaults and no vendor lock-in,
- a **board harness generated from flags** for simulation peripherals,
- project facts read from the project itself, so the same command works in any
  AVR or Cortex-M tree.

## Install

```sh
pipx install git+https://github.com/luimu64/mcu-cli    # recommended
# or
pip install git+https://github.com/luimu64/mcu-cli
# or, from a checkout
pip install -e .
```

Requires Python ≥ 3.9 (the optional config file needs ≥ 3.11 for `tomllib`).
Run `mcu doctor` to see which of the underlying tools are present and what to
install for the rest.

| capability | needs |
|---|---|
| `build`, `clean`, `size` | `cmake`, `ninja`, `avr-gcc` + `avr-objcopy` (or `arm-none-eabi-gcc` + newlib — a separate package on Debian/Ubuntu: `libnewlib-arm-none-eabi`) |
| `flash` (AVR) | `avrdude` |
| `flash` (ARM) | `pyocd` |
| `monitor` | `picocom` |
| `sim`, `board`, `trace` | `simavr` (+ `libsimavrparts`, usually packaged with it) |
| `debug` (simulated) | `simavr`, `avr-gdb` |
| `debug --hw` (ARM) | `pyocd`, `arm-none-eabi-gdb` |

simavr has no `--version`; `mcu doctor` reports it by counting the cores it knows.

## Quick start

```sh
mcu new blink --led D13 --button D2       # CMake + toolchain + src/main.c
cd blink
mcu build                                 # -> build/blink.elf/.hex/.bin + size report
mcu flash                                 # USB bootloader; --method usbasp for ICSP
mcu monitor                               # serial console (autodetects the port)
```

Nothing plugged in? Everything except `flash`/`monitor` still works, and
`mcu flash --dry-run` shows exactly what would be sent.

## Commands

| command | purpose |
|---|---|
| `doctor` | inventory: toolchain versions, AVR + ARM, simulator, serial ports, probes, and install hints for whatever is missing |
| `list cores\|parts` | MCUs simavr emulates / peripheral parts available to the harness |
| `new PATH` | scaffold a project (`--arch avr\|arm`, `--led`, `--button`, `--mcu`, `--freq`, …) |
| `build` | cmake configure (once) + `cmake --build`; `--reconfigure` to force the first step |
| `clean` | remove `build/` and generated simulation sources |
| `size` | flash/RAM report (`avr-size --format=avr`, or `arm-none-eabi-size`) |
| `flash` | `avrdude -c arduino` (bootloader), `-c usbasp` (ICSP), or `pyocd flash` for ARM |
| `monitor` | `picocom` on the autodetected port |
| `sim` | plain simavr run (colourised library UART output) |
| `board` | simavr **plus peripherals**: LEDs, buttons, scripted/injected serial |
| `debug` | `simavr -g` + `avr-gdb`; `--hw` uses a real probe via `pyocd` |
| `trace` | VCD trace of register/IRQ activity, summarised on exit |

Global: `-C DIR` (project directory; default searches upwards from the cwd),
`-n/--dry-run`, `--verbose`.

## Peripherals in simulation

simavr's core emulates the MCU only; LEDs, buttons, displays and serial sinks live in
`libsimavrparts` and must be wired to the core's IRQs by a host program. `mcu board`
generates that program from flags, compiles it and runs it:

```sh
mcu board --led D13 --led D9 --button D2 \
          --press 1.5s:150ms --press 3.5s:150ms \
          --rx 1.2s:abc --seconds 8
```

| flag | meaning |
|---|---|
| `--led PIN` | observe an output pin; Arduino labels (`D13`, `A0`) or raw pins (`PB5`); repeatable |
| `--button PIN` | attach a button part driving that pin; repeatable |
| `--press [BTN:]AT:HOLD` | scripted press at a simulated time; durations accept `500`, `150ms`, `1.5s`, `2m` |
| `--rx AT:TEXT` | inject serial input at a simulated time |
| `--seconds N` | stop after N **simulated** seconds (8 s of firmware runs in about a second) |
| `--no-uart`, `--no-keys` | turn off the UART sink / the interactive keys |

Interactively: `b` presses button 0, `q` quits, any other key is fed to the UART RX.
The generated source is `sim/generated/board.c` (regenerated on every run — do not
edit it) and the binary is `sim/generated/board`. Details, including which IRQs to
hook and why: [docs/simulator.md](docs/simulator.md).

## Debug and traces

```sh
mcu debug                                                   # interactive gdb
mcu debug --batch -x 'break uart_init' -x continue -x bt -x 'x/1xb 0x8000C4'
mcu trace --seconds 3 -o ports.vcd                          # PORTB/PORTD/SECONDS
mcu trace --signal 'PB5=portpin@0x5/0x42' --seconds 2
```

- Registers live in AVR data space, `0x800000 + datasheet address`, written with six
  hex digits: `x/1xb 0x8000C4` is `UBRR0L`, `0x800025` is `PORTB`.
- `--batch` appends `detach` and wraps gdb in a timeout, so a stray `continue` cannot
  hang a script.
- `sram8`/`sram16` traces record *changes*, not values — pair them with a gdb read at
  a breakpoint to get values with timing.

## Configuration

Optional `~/.config/mcu/config.toml` (or `$XDG_CONFIG_HOME/mcu/config.toml`); every CLI
flag overrides it:

```toml
[defaults]
mcu    = "atmega328p"
freq   = "16000000"
port   = "/dev/ttyUSB0"
baud   = 115200
build_type = "Release"
simavr_prefix = "/usr/local"
led    = ["D13"]
button = ["D2"]
press  = ["1.5s:150ms"]
```

`SIMAVR_PREFIX` in the environment overrides `simavr_prefix` (useful when simavr is
installed under `/usr` rather than `/usr/local`).

## How it works

- **Project facts, not config:** `MCU`, `F_CPU` and the target name come from
  `CMakeCache.txt` when the project is configured, otherwise from `CMakeLists.txt`;
  AVR vs ARM is decided by which toolchain file the project references. That is why
  `mcu build` works from any subdirectory of any project.
- **Generated, not hand-written:** `new` writes project files from templates
  (avr-libc or Cortex-M, including a linker script, a C startup file and editor debug
  config), and `board` writes the simavr harness. Both are regenerable and disposable.
- **No vendor lock-in:** everything it runs is a normal open-source tool. `--verbose`
  echoes every command, `--dry-run` prints them without running.

See [examples/nano-blink](examples/nano-blink) for a complete project, and
[docs/troubleshooting.md](docs/troubleshooting.md) for the failure modes that are
worth knowing up front.

## Platform support

Linux and macOS. The harness and simulator paths assume a POSIX host; Windows is
untested (WSL2 should work). Serial-port discovery covers `/dev/ttyUSB*`,
`/dev/ttyACM*`, `/dev/serial/by-id/*` and the macOS `cu.*`/`tty.usb*` names.

## Limitations

- Simulated debugging (`sim`, `board`, `debug`, `trace`) is AVR-only: simavr is an AVR
  simulator. Cortex-M flashing/debugging needs real hardware.
- The scaffolder targets ATmega328P-class parts (the demo uses `UCSR0A`/`PCINT`
  registers); other parts build and flash fine, but edit the UART/interrupt code.
- `mcu` does not manage toolchain installation — `mcu doctor` tells you what to install.

## Development

```sh
python -m unittest discover -s tests -v      # integration tests self-skip without toolchains
```

CI runs the suite on Python 3.9/3.11/3.13, and a second job installs the AVR and ARM
toolchains so the build/compile tests execute for real.

## License

MIT — see [LICENSE](LICENSE).
