# Simulation with peripherals

simavr emulates the MCU: instruction-accurate core, timers, USART, GPIO, interrupts.
It does **not** have LEDs or buttons — nothing in the core model represents a user
pressing a switch or a lamp on a pin. Peripherals are separate C objects in
`libsimavrparts` that you wire to the core's IRQs from a host program. `mcu board`
generates that program for you; this document explains what it does and how to extend
it by hand.

Everything is IRQ-based, which is what makes this work: the emulated core raises
interrupt-request objects for register writes, pin changes and serial bytes, and a
part is simply something that listens to one and/or drives another.

## LEDs (output pins)

A write to a PORT register raises the port-wide IRQ `IOPORT_IRQ_PIN_ALL` with the
**whole 8-bit pin state**. Pick your bit out of the byte:

```c
avr_irq_register_notify(
    avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('B'), IOPORT_IRQ_PIN_ALL),
    led_hook, NULL);

static void led_hook(struct avr_irq_t *irq, uint32_t value, void *param)
{
    int pb5 = (value >> 5) & 1;      /* PB5, for example */
}
```

**The trap that costs people an hour:** IRQ indices `IOPORT_IRQ_PIN0`..`PIN7` are the
*input* side of the port (they feed stimulus *into* the core). A notify registered on a
single-pin IRQ never fires for a pin the firmware drives. Use `PIN_ALL` (index 8) for
outputs, and `IOPORT_IRQ_REG_PORT` (index 10) if you want the register itself.

One notify per port is enough — `mcu board` registers one per distinct port and
demultiplexes.

## Buttons (input pins)

The `button` part drives its output IRQ and can auto-release:

```c
button_t b;
button_init(avr, &b, "D2");
avr_connect_irq(b.irq + IRQ_BUTTON_OUT,
                avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('D'), 2));   /* PD2 */

button_press(&b, 150000);   /* hold the pin low for 150 ms, then release */
button_release(&b);         /* or release manually */
```

The firmware must latch the press where an interrupt can see it. A main loop that
samples the pin once per 500 ms delay misses a 150 ms press completely — the generated
demo uses a PCINT interrupt that only sets a flag, and prints from the main loop
(printing from interrupt context is not safe).

## Serial, both directions

```c
avr_irq_register_notify(                        /* MCU -> host */
    avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_OUTPUT),
    uart_hook, NULL);

avr_raise_irq(                                  /* host -> MCU */
    avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_INPUT), 'x');
```

Bytes raised on `UART_IRQ_INPUT` before the firmware has set `RXEN` are dropped
(`avr_uart_irq_input()` checks the enable bit), which is why injections are scheduled
rather than sent at t=0.

## Scheduling

`avr_cycle_timer_register_usec()` fires **relative to now**, and re-registering the
same `(callback, param)` pair cancels the earlier timer. Schedule N events with N
distinct params, or only the last survives. The generated harness gives every
scheduled press and injection its own config struct for exactly that reason.

Timers run on *simulated* time: `--press 1.5s:150ms` means 1.5 s of emulated CPU time,
not 1.5 s of wall clock. Simulation normally runs faster than real time (8 s of
firmware in about a second).

## Other parts

The same pattern covers everything in `libsimavrparts` — see `mcu list parts`:

| part | what it models |
|---|---|
| `hd44780` | character LCD |
| `ssd1306_virt`, `sh1106_virt` | OLED displays (virtual framebuffer) |
| `i2c_eeprom` | I²C EEPROM |
| `hc595` | shift register (drives 8 outputs from 3 pins) |
| `rotenc` | rotary encoder |
| `uart_pty`, `uart_udp` | serial over a pty or UDP instead of stdout |

To use one, add the part to the generated harness (or copy it out of
`sim/generated/board.c` and keep your own), `#include` its header, create it, and
connect its IRQs to the pins it belongs to. The link flags stay the same:
`-lsimavrparts -lsimavr -lelf -lm`, headers under `$SIMAVR_PREFIX/include/simavr/parts`.

## Traces instead of watches

For "what did this pin/register do over time", use `mcu trace`:

```sh
mcu trace --seconds 3 -o ports.vcd                 # PORTB, PORTD, a stack variable
mcu trace --signal 'PB5=portpin@0x5/0x42' --seconds 2
```

Signal forms (`-at NAME=KIND@ADDR/MASK`, hex must be `0x`-prefixed):

| kind | meaning |
|---|---|
| `sram8@0xADDR`, `sram16@0xADDR` | change activity at a data-space address |
| `irq@<slot>/0xff` | interrupt vector activity |
| `portpin@<BIT>/<PORT-LETTER>` | one external pin — note the CLI's fields are swapped relative to the ELF-tag encoding (pin first, then the ASCII port letter) |
| `ioirq@<4-char ioctl>/<index>` | an I/O module IRQ, e.g. `iogB` = IOPORT B |

Behaviour worth knowing:

- `sram8`/`sram16` record *changes*, not values. Use them for timing (a firmware
  toggling every 500 ms produces deltas of 500.0/501.3 ms) and read values with gdb.
- IOPORT IRQ indices 0–7 are inputs, so a `portpin` trace of a driven output stays
  `x`. Use the port register address with `sram8` (ATmega328P: PORTB `0x25`, PORTD
  `0x2B`).
- The port-register trace (`ioirq@iogB/10`) stalled after one event in simavr 1.8.
- `-t` (full instruction trace) requires a build with `CONFIG_SIMAVR_TRACE`.

## Register and memory inspection

From `mcu debug` (an `avr-gdb` session against the simulator):

```
x/1xb 0x8000C4     # UBRR0L     (data space = 0x800000 + datasheet address)
x/1xb 0x8000C0     # UCSR0A     (0x22 = U2X0|UDRE0)
x/1xb 0x800025     # PORTB
```

A 9-digit address such as `0x800000C4` fails with "Cannot access memory at address";
AVR data space needs six hex digits of offset.

Hardware watchpoints on SFRs are not usable — break on a function that runs often and
print the register to build a value sequence alongside a trace.
