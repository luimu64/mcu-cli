# mcu — one CLI for the embedded workflow

[![ci](https://github.com/luimu64/mcu-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/luimu64/mcu-cli/actions/workflows/ci.yml)

Scaffold, build, flash, monitor, **simulate with LEDs and buttons**, debug and trace —
AVR and Cortex-M, from one command, without a vendor IDE.

```
$ mcu board --led D13 --button D2 --press 1.5s:150ms --rx 1.2s:abc --seconds 8
  leds:1  buttons:1  uart:on   keys: 'b' press, 'q' quit, other = serial RX
  --------------------------------------------------------------
[led         0.02 ms] D13   -> ON   (PORTB=0x20)
tick
[led       500.96 ms] D13   -> off  (PORTB=0x00)
tick
[led      1001.91 ms] D13   -> ON   (PORTB=0x20)
tick
[uart_rx  1200.00 ms] inject "abc"
[button   1500.00 ms] press PD2 (hold 150 ms)
press
a
[led      1504.54 ms] D13   -> off  (PORTB=0x00)
tick
button_auto_release
b
[led      2006.05 ms] D13   -> ON   (PORTB=0x20)
tick
c
```

`tick`/`press`/`a` come from the scaffolded firmware's demo block; the `[led …]` and
`[button …]` lines come from the generated harness.

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

simavr has no `--version`; `mcu doctor` reports it by counting the cores it knows, and
probes which optional flags it accepts. Debian/Ubuntu still ship **simavr 1.6**, which
has no `-g <port>`, `-at <signal>` or `-o <file>` (it reads the flag's *value* as the
firmware name) — `mcu` detects that and falls back to the bare `-g` on port 1234 and to
writing the VCD via stdout, and refuses signal traces with a hint instead of a mystery
error. Set `MCU_SIMAVR_FLAGS=gdb_port,signal,output` to override the probe.

## Quick start

```sh
mcu new blink --led D13 --button D2       # CMake + toolchain + src/main.c
cd blink
mcu build                                 # -> build/blink.elf/.hex/.bin + size report
mcu flash                                 # USB bootloader; --method icsp for ICSP
mcu monitor                               # serial console (autodetects the port)
```

The generated `src/main.c` is a working skeleton: pin/UART/interrupt plumbing you keep,
plus one block marked `YOUR CODE HERE` — a demo heartbeat (`tick`, `press`, serial echo)
that exists so `sim`/`board` have something to show. Replace that block with your own
firmware; everything above it is what the CLI and the board harness expect.

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
| `flash` | `avrdude -c arduino` (bootloader), a programmer via `--method icsp` (default `-c usbasp`, `--programmer` for anything else), or `pyocd flash` for ARM |
| `fuses` | classic AVR8: read/write `lfuse`/`hfuse`/`efuse` (`avrdude -U`), flip the debugWIRE `DWEN` bit with `--dwen on\|off`. AVR8X: read the `fuse0…fuse8` block over UPDI and write bytes by name (`--fuse SYSCFG0=0xF6`) |
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
mcu debug --batch -x 'break uart_putchar' -x continue -x bt -x 'x/1xb 0x8000C4'
mcu trace --seconds 3 -o ports.vcd                          # PORTB/PORTD/SECONDS
mcu trace --signal 'PB5=portpin@0x5/0x42' --seconds 2
```

- Registers live in AVR data space, `0x800000 + datasheet address`, written with six
  hex digits: `x/1xb 0x8000C4` is `UBRR0L`, `0x800025` is `PORTB`.
- `--batch` appends `detach` and wraps gdb in a timeout, so a stray `continue` cannot
  hang a script.
- `sram8`/`sram16` traces record *changes*, not values — pair them with a gdb read at
  a breakpoint to get values with timing.

## Flashing a bare chip over ISP

`--method icsp` hands the job to a real programmer. The programmer id is an avrdude
`-c` value, so any probe avrdude knows works without a special case:

```sh
mcu flash --method icsp                                  # -c usbasp (default)
mcu flash --method icsp --programmer atmelice_isp -B 10  # Atmel-ICE, SPI/ISP
mcu flash --method icsp --programmer atmelice_dw         # Atmel-ICE, debugWIRE
mcu flash --method icsp --programmer jtag3isp -P usb     # JTAGICE3
```

| flag | meaning |
|---|---|
| `--programmer ID` | avrdude `-c` id: `usbasp`, `atmelice_isp`, `atmelice_dw`, `jtag3isp`, `dragon_isp`, `usbtiny`, … |
| `-B US` | avrdude `-B`, the ISP SCK period in microseconds |
| `--port P` | passed through as avrdude `-P` (`usb` for most USB probes); the bootloader autodetect does not leak into this path |

`--programmer`/`-B` are refused with `--method bootloader` (a bootloader has no probe and
no ISP clock) and on ARM projects (pyocd is already the probe).

**A factory-fresh part needs `-B`.** ISP SCK must stay below a quarter of the target
clock, and a new ATmega328P runs on its internal 8 MHz RC divided by 8 = **1 MHz**, so
avrdude's default is too fast and the chip answers nothing. Start at `-B 10` and only
speed up once it works. If the low fuse already selects a crystal, the crystal and its
load capacitors must be fitted or the chip has no clock at all.

## Fuses and debugWIRE (DWEN)

`mcu fuses` reads and writes the fuse bytes. There are two families and the command
picks the right one from the project's MCU:

- **Classic AVR8** (ATmega328P, ATmega2560, …): three bytes `lfuse`/`hfuse`/`efuse`, written
  over ISP; `--dwen` flips the one bit that switches between ISP and debugWIRE.
- **AVR8X** (ATmega4809, ATtiny1616, …): one 10-byte block at `0x1280` — `fuse0…fuse8`,
  named `WDTCFG`, `BODCFG`, `OSCCFG`, `TCD0CFG`, `SYSCFG0`, `SYSCFG1`, `APPEND`,
  `BOOTEND` — written over **UPDI** (drop the classic `--lfuse/--hfuse/--efuse` habit;
  the command refuses them and tells you which byte each one became).

Unprogrammed = 1, programmed = 0, so for classic parts
**DWEN programmed means bit 6 of hfuse is cleared** (ATmega328P: `0xD9` → `0x99`).

```sh
# classic AVR8 over ISP
mcu fuses --programmer atmelice_isp -B 10             # read + decode
mcu fuses --programmer atmelice_isp -B 10 --dwen on   # enable debugWIRE
mcu fuses --programmer atmelice_isp -B 10 --dwen off  # back to ISP
mcu fuses --programmer atmelice_isp -B 10 --lfuse 0xFF --hfuse 0xD9 --efuse 0xFF

# AVR8X over UPDI
mcu fuses --programmer atmelice_updi                  # read the whole block + decode
mcu fuses --programmer atmelice_updi --fuse SYSCFG0=0xF6
mcu fuses --programmer atmelice_updi --fuse OSCCFG=0x7F --fuse fuse8=0x02
```

```
$ mcu fuses --programmer atmelice_isp -B 10
==> read fuses
lfuse=0x62 hfuse=0xD9 efuse=0xFF
     hfuse bits, classic AVR order: RSTDISBL=1 DWEN=1 SPIEN=0 WDTON=1 EESAVE=1 BOOTSZ1=0 BOOTSZ0=0 BOOTRST=1
     DWEN unprogrammed (debugWIRE off); SPIEN programmed (ISP usable)

$ mcu fuses --programmer atmelice_updi          # ATmega4809, read-only
==> read fuses
fuses@0x1280 = 00 00 7E FF FF F6 FF 00 00 00
     0 WDTCFG=0x00  1 BODCFG=0x00  2 OSCCFG=0x7E  3 FUSE3=0xFF  4 TCD0CFG=0xFF
     5 SYSCFG0=0xF6  6 SYSCFG1=0xFF  7 APPEND=0x00  8 BOOTEND=0x00  9 FUSE9=0x00
     OSCCFG (megaAVR 0-series names): FREQSEL=(0x7E & 0x03) >> 0 = 2; OSCLOCK=(0x7E & 0x80) >> 7 = 0
     SYSCFG0 (megaAVR 0-series names): EESAVE=(0xF6 & 0x01) >> 0 = 0; RSTPINCFG=(0xF6 & 0x08) >> 3 = 0 (PA0 is a plain I/O pin); CRCSRC=(0xF6 & 0xc0) >> 6 = 3
```

- `--dwen on|off` is a read-modify-write: it reads the current hfuse first (so only bit 6
  moves, whatever else the chip has set), writes it back and reads all three again.
  It is idempotent — an hfuse already in the wanted state is not written.
- **DWEN takes ISP away.** Once it is programmed and the target is power-cycled,
  debugWIRE owns RESET and ISP is unreachable *even with SPIEN programmed*. Flash and
  EEPROM stay programmable over debugWIRE (`-c atmelice_dw`); fuses do not — avrdude
  reports `ISP activation failed, trying debugWIRE` and `Please restart avrdude without
  power-cycling the target`. `mcu` recognises that, warns and retries once, which is the
  documented way through. `mcu flash` over ISP points at `mcu fuses --dwen off` when it
  fails for the same reason.
- `--dwen off` refuses to write when SPIEN is unprogrammed, because ISP cannot reach the
  chip any more: disable debugWIRE from inside a debugWIRE session instead
  (`avrdude -c atmelice_dw -p m328p -t`, then `monitor debugwire disable`).
- `RSTDISBL` (hfuse bit 7) turns RESET into an I/O pin and kills both interfaces, and
  DWEN **plus** lock bits has no software way back: those need a high-voltage programmer
  (STK500, AVR Dragon) — the Atmel-ICE has no HVPP/HVSP.
- The bit positions above are the classic AVR8 (mega/tiny) map. ATmega328P defaults are
  `lfuse=0x62, hfuse=0xD9, efuse=0xFF` (internal 8 MHz ÷ 8, SPIEN on) and
  `0xFF/0xD9/0xFF` selects a full-swing 16 MHz crystal. Read the datasheet table before
  writing anything — a wrong low fuse is how a chip stops answering ISP.

### AVR8X: there is no DWEN, and no lfuse

Two things are *structurally* different, not just renamed:

- **No DWEN.** AVR8X debugs over UPDI from reset — there is nothing to enable, so
  `--dwen` is refused instead of being accepted as a no-op. The nearest equivalent is
  `SYSCFG0.RSTPINCFG` (bit 3): `0` = PA0 is a plain I/O pin (the ATmega4809 default,
  `FUSE_SYSCFG0_DEFAULT 0xF6`), `1` = PA0 drives RESET for the application — after which
  a debugger needs the **"UPDI enable with fuse override"** sequence to get back in.
  `mcu fuses --fuse SYSCFG0=0xFE` warns in exactly that direction before writing.
- **No ISP path at all.** AVR8X has no serial bootloader and no ISP, so `mcu flash`
  demands a UPDI programmer (`atmelice_updi`, `serialupdi`, `jtag2updi`, or the
  Curiosity Nano's `pkobn_updi`) rather than silently trying `usbasp`:
  `mcu flash --method icsp --programmer atmelice_updi`.
- The bit names printed for `OSCCFG`/`SYSCFG0` are the **megaAVR 0-series** ones (verified
  against avr-libc's `iom4809.h`: `EESAVE` bit 0, `RSTPINCFG` bit 3, `CRCSRC` bits 7:6,
  `FREQSEL` bits 1:0, `OSCLOCK` bit 7). tinyAVR 2-series move them (e.g.
  `SYSCFG0.UPDIPINCFG`) — read that part's datasheet before writing.
- `fuse3`/`fuse4` are absent on some parts and `CODESIZE`/`BOOTSIZE` are the same bytes as
  `APPEND`/`BOOTEND`: `--fuse CODESIZE=0x01` writes `fuse7`.

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

- Simulated debugging (`sim`, `board`, `debug`, `trace`) is AVR-only *and* classic-AVR8-only:
  simavr has no megaAVR 0-series / tinyAVR 0–2 core, so AVR8X parts are refused with a hint
  instead of a mystery (`mcu flash` + `mcu monitor` is the AVR8X workflow). Cortex-M
  flashing/debugging needs real hardware.
- The scaffolder emits two templates and picks by MCU: classic AVR8 (`UCSR0A`/`PCINT`) and
  AVR8X (`USART0`/`PORTx.PINnCTRL`). Both compile clean with `-Wall -Wextra`; other parts
  build and flash fine, but check the UART/interrupt registers of a family that has
  neither (e.g. older ATtiny).
- `mcu` does not manage toolchain installation — `mcu doctor` tells you what to install.

## Development

```sh
python -m unittest discover -s tests -v      # integration tests self-skip without toolchains
```

CI runs the suite on Python 3.9/3.11/3.13, and a second job installs the AVR and ARM
toolchains so the build/compile tests execute for real.

## License

MIT — see [LICENSE](LICENSE).
