# Troubleshooting

Most failures here fall into a handful of categories. `mcu doctor` first: it reports
which tools are installed, which probes and serial ports are visible, and how to
install anything missing.

## Build

**`unrecognized command line option -mmcu=` / `-mthumb`, or the host compiler complains.**
The toolchain file was not passed at configure time. Delete `build/` and reconfigure:

```sh
rm -rf build && mcu build --reconfigure
```

`mcu build` always passes `-DCMAKE_TOOLCHAIN_FILE=<arch>-gcc.cmake`; a stale `build/`
configured by hand (or by an editor) is the usual cause.

**`no CMakeLists.txt found ... upwards`.** `mcu` resolves the project by walking up from
the current directory. Run it inside the project or pass `-C /path/to/project`.

**`#error "This demo targets the ATmega328P"`.** The scaffold's guard. Delete it (or
change it) when building for another part; it exists so a mis-set `--mcu` fails loudly
instead of producing code for the wrong chip.

## Flashing

**`avrdude: stk500_recv(): programmer is not responding`.** Either the wrong bootloader
baud (official Nano boards are 57600, most clones are 115200 — try both) or something
else is holding the port (close the serial monitor first).

**`avrdude` can't open the port / permission denied.** Your user needs to be in the
group that owns the device (usually `uucp` or `dialout`):

```sh
sudo usermod -aG uucp "$USER"     # then log out and back in
```

**`no serial port found`.** The board is unplugged, the cable is charge-only, or the
USB-serial driver is missing (`dmesg | tail` after plugging it in). `mcu doctor` lists
what it can see.

**`avrdude: initialization failed, rc=-1`** over ICSP: wiring, target power, or the
wrong programmer (`-c usbasp` expects a USBasp; a SNAP or Atmel-ICE needs its own
`-c` name — pass it through with `mcu flash --method usbasp` and adjust, or call
`avrdude` directly for exotic programmers).

**Fuses.** `mcu` never writes fuses. Read them first and write them deliberately —
a wrong `hfuse` on a board with a bootloader bricks the bootloader, not the chip, but
recovering needs ICSP.

## Monitor

**Garbage characters.** Baud mismatch, or the board is running on a different clock
than the firmware assumes (`F_CPU` vs the actual crystal). Some clones also garble
115200 because 16 MHz cannot hit it exactly (+2.1 % with double-speed mode, which is
what both this scaffold and the Arduino core use); 57600 or 38400 are safer.

**Nothing at all.** Opening the port asserts DTR, which resets the board — anything
printed before you attached is gone. Also check that the firmware actually enabled
`TXEN` and that you are on the right port.

## Simulation

**`--led D13` shows nothing.** The firmware never writes that port bit (with
`mcu board --led`, a static pin prints nothing — only changes are reported), or the pin
is on a port the harness did not register. Multiple LEDs on different ports are fine;
they are demultiplexed per port.

**A button press has no effect.** The firmware must latch it in an interrupt. A loop
that polls the pin once per 500 ms misses a 150 ms press; use PCINT/INTx and set a flag.

**The UART prints everything twice (or with `..` and colour codes).** Two writers: the
library's own UART printer (`AVR_LOG(..., LOG_OUTPUT, ...)`, which renders control
characters as `.`) plus your hook. The generated harness sets `avr->log = 0` to silence
the library so only its hook writes.

**`--rx` bytes are ignored.** They were raised before the firmware set `RXEN`. Schedule
the injection after startup (`--rx 1.2s:abc`, not `--rx 0s:abc`).

**`ELF format is not supported by this build`.** simavr was compiled without libelf
support (the Arch AUR package does this: its build line overrides `CFLAGS`, dropping
`-DHAVE_LIBELF=1`). Rebuild simavr with the define in `CFLAGS`, or feed it a `.hex` and
lose symbols.

**The harness fails to compile with `sim_avr.h: No such file`.** simavr is not installed
where `mcu` looks. Point it at the prefix:

```sh
export SIMAVR_PREFIX=/usr          # or wherever include/simavr/parts lives
```

## Debug

**`avr-gdb` hangs at `target remote`.** Another client is attached (simavr's stub
accepts exactly one connection), or an earlier `mcu debug` left a simulator running.
`pkill -f 'simavr .*mcu'` and retry. Do not "test" the gdb port with a TCP connect:
that consumes the single slot.

**`Cannot access memory at address 0x800000C4`.** One digit pair too many. AVR data
space is `0x800000 + address` with six hex digits: `0x8000C4`.

**A `--batch` debug run never returns.** It ends with `detach` on purpose; a trailing
`continue` with no breakpoint left runs forever. `--batch` wraps gdb in a timeout so
this fails loudly instead of hanging, and `--timeout N` tunes it.

## Traces

**The VCD stops growing after the first event.** Known simavr 1.8 behaviour for the
port-register trace (`ioirq@.../10`). Use `sram8@<register address>` instead.

**Values look like gibberish / everything is `x`.** `sram` traces carry change events,
not values; `portpin` traces of a driven (output) pin stay `x` because pin IRQs are the
input side. Read values from gdb.
