# nano_blink

Bare-metal AVR firmware (atmega328p, 16000000 Hz, avr-libc only — no Arduino core).

```sh
mcu build      # cmake + ninja -> build/nano_blink.elf/.hex/.bin/.map
mcu size       # flash/RAM report
mcu flash      # USB bootloader (--method icsp for a programmer)
mcu monitor    # serial console
mcu sim        # run under simavr
mcu board --led D13 --button D2 --press 1.5s:150ms --seconds 8
mcu debug      # breakpoints/stepping against simavr
mcu trace      # VCD I/O trace
```

Hardware map: LED on PB5 (D13), button on PD2
(D2, internal pull-up, PCINT18 interrupt), UART at 115200 Bd on PD0/PD1.
