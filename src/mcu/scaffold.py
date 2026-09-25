"""Project scaffolding: AVR (avr-libc) and Cortex-M (bare metal) starters.

Templates use @TOKEN@ substitution rather than str.format so CMake's ${...}
syntax needs no escaping.
"""

from __future__ import annotations

import os

from .util import (avr8x_ports, die, info, is_avr8x, ok, parse_label,
                   parse_portpin, pcint_for)


def render(text: str, **kw) -> str:
    for key, value in kw.items():
        text = text.replace(f"@{key.upper()}@", str(value))
    return text


# --------------------------------------------------------------------------
# AVR (avr-libc, no Arduino core)
# --------------------------------------------------------------------------

AVR_CMAKELISTS = """\
cmake_minimum_required(VERSION 3.20)

# Board/part configuration — override at configure time:
#   cmake -B build -DMCU=atmega328p -DF_CPU=16000000
set(MCU   "@MCU@" CACHE STRING "AVR part, passed to avr-gcc -mmcu=")
set(F_CPU "@FREQ@" CACHE STRING "CPU clock in Hz")

project(@NAME@ C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_compile_options(
  -mmcu=${MCU}
  -DF_CPU=${F_CPU}UL
  -Os -g -Wall -Wextra
  -ffunction-sections -fdata-sections -fno-common
)
add_link_options(-mmcu=${MCU} -Wl,--gc-sections -Wl,-Map=${PROJECT_NAME}.map)

add_executable(${PROJECT_NAME} src/main.c)
set_target_properties(${PROJECT_NAME} PROPERTIES SUFFIX ".elf")

# avr-objcopy is what the programmer actually eats: hex (+ bin/map for other tools)
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
  COMMAND avr-objcopy -O ihex   -R .eeprom $<TARGET_FILE:${PROJECT_NAME}> ${PROJECT_NAME}.hex
  COMMAND avr-objcopy -O binary -R .eeprom $<TARGET_FILE:${PROJECT_NAME}> ${PROJECT_NAME}.bin
  COMMAND avr-size --format=avr --mcu=${MCU} $<TARGET_FILE:${PROJECT_NAME}>
  COMMENT "elf -> hex/bin + size report"
  VERBATIM
)
"""

AVR_TOOLCHAIN = """\
# CMake toolchain file for bare-metal AVR. Always pass it at configure time:
#   cmake -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE=avr-gcc.cmake
# Without it CMake uses the host cc and "succeeds" until it hits -mmcu=.
set(CMAKE_SYSTEM_NAME      Generic)
set(CMAKE_SYSTEM_PROCESSOR avr)

set(CMAKE_C_COMPILER   avr-gcc)
set(CMAKE_CXX_COMPILER avr-g++)
set(CMAKE_ASM_COMPILER avr-gcc)

set(CMAKE_OBJCOPY avr-objcopy)
set(CMAKE_OBJDUMP avr-objdump)
set(CMAKE_SIZE    avr-size)

# There is no CRT to link against on a bare target: link tests must build a
# static library instead of an executable, or the compiler check fails.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
"""

AVR_MAIN = """\
/*
 * @NAME@ — bare-metal AVR skeleton (avr-libc only, no Arduino core).
 *
 *   @LED_LABEL@ LED -> P@LED_PORT@@LED_BIT@
 *   @BTN_LABEL@ button -> P@BTN_PORT@@BTN_BIT@ : to GND, internal pull-up, PCINT
 *   TXD -> PD1, RXD -> PD0 : UART, @BAUD@ Bd
 *
 * `mcu build`, simulate with `mcu board --led @LED_LABEL@ --button @BTN_LABEL@`.
 * Everything above the marked block is the plumbing the CLI and the generated
 * board harness rely on; your firmware goes inside the block in main().
 */

#ifndef F_CPU
#define F_CPU @FREQ@UL
#endif
#define BAUD @BAUD@UL

#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdio.h>
#include <util/delay.h>

#define LED_PORT  PORT@LED_PORT@
#define LED_DDR   DDR@LED_PORT@
#define LED_BIT   @LED_BIT@

#define BTN_PORT  PORT@BTN_PORT@
#define BTN_PIN   PIN@BTN_PORT@
#define BTN_DDR   DDR@BTN_PORT@
#define BTN_BIT   @BTN_BIT@

/* Double-speed (U2X) divisor: UBRR = F_CPU / (8 * BAUD) - 1.
 * 16 MHz/115200 -> 117647 Bd, +2.1 % (single speed would be -3.5 %). */
#define UBRR_VAL ((F_CPU / (8UL * BAUD)) - 1UL)

static int uart_putchar(char c, FILE *stream)
{
    (void)stream;
    if (c == '\\n') {
        uart_putchar('\\r', stream);
    }
    loop_until_bit_is_set(UCSR0A, UDRE0);
    UDR0 = (uint8_t)c;
    return 0;
}
static FILE uart_stdout = FDEV_SETUP_STREAM(uart_putchar, NULL, _FDEV_SETUP_WRITE);

static void io_init(void)
{
    UBRR0H = (uint8_t)(UBRR_VAL >> 8);
    UBRR0L = (uint8_t)UBRR_VAL;
    UCSR0A = _BV(U2X0);
    UCSR0B = _BV(TXEN0) | _BV(RXEN0);
    UCSR0C = _BV(UCSZ01) | _BV(UCSZ00);      /* 8 data bits, no parity, 1 stop */

    LED_DDR |= _BV(LED_BIT);
    BTN_DDR &= (uint8_t)~_BV(BTN_BIT);
    BTN_PORT |= _BV(BTN_BIT);                /* internal pull-up */
    PCMSK@PCINT_GROUP@ |= _BV(PCINT@PCINT_NUM@);
    PCICR |= _BV(PCIE@PCINT_GROUP@);
    sei();
}

/* The ISR only latches the event: printing from interrupt context is not safe,
 * and a polling loop would miss a short press. */
volatile uint8_t button_pressed;

ISR(PCINT@PCINT_GROUP@_vect)
{
    if (!(BTN_PIN & _BV(BTN_BIT))) {         /* pull-up high = released */
        button_pressed = 1;
    }
}

int main(void)
{
    io_init();

    for (;;) {
        /* ---------------------- YOUR CODE HERE ----------------------
         * Demo heartbeat, so `mcu board` / `mcu sim` show something
         * before you write yours: replace this whole block.
         */
        if (button_pressed) {
            button_pressed = 0;
            fprintf(&uart_stdout, "press\\n");
        }
        if (UCSR0A & _BV(RXC0)) {            /* demo: echo serial input */
            uart_putchar(UDR0, &uart_stdout);
            uart_putchar('\\n', &uart_stdout);
        }
        LED_PORT ^= _BV(LED_BIT);
        fprintf(&uart_stdout, "tick\\n");
        _delay_ms(500);
        /* ---------------------- END OF DEMO ---------------------- */
    }
}
"""


# --------------------------------------------------------------------------
# Cortex-M (bare metal, no vendor HAL)
# --------------------------------------------------------------------------

ARM_CMAKELISTS = """\
cmake_minimum_required(VERSION 3.20)

set(CPU_FLAGS -mcpu=@CPU@ -mthumb @FLOAT_ABI@ CACHE STRING "compiler CPU flags")
set(LINKER_SCRIPT "@LDSCRIPT@" CACHE STRING "linker script")

project(@NAME@ C)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)   # clangd/clang-based editors pick this up

# the link step runs from the build dir, so resolve a relative script against the
# source dir (an absolute path is honoured as-is)
if(NOT IS_ABSOLUTE "${LINKER_SCRIPT}")
  set(LINKER_SCRIPT "${CMAKE_SOURCE_DIR}/${LINKER_SCRIPT}")
endif()
if(NOT EXISTS "${LINKER_SCRIPT}")
  message(FATAL_ERROR "linker script not found: ${LINKER_SCRIPT}")
endif()

add_executable(${PROJECT_NAME}.elf src/startup.c src/main.c)
set_target_properties(${PROJECT_NAME}.elf PROPERTIES SUFFIX "")

target_compile_options(${PROJECT_NAME}.elf PRIVATE ${CPU_FLAGS}
  -g3 -O0 -Wall -Wextra -ffunction-sections -fdata-sections)
target_link_options(${PROJECT_NAME}.elf PRIVATE ${CPU_FLAGS}
  -T ${LINKER_SCRIPT} -nostartfiles
  -Wl,--gc-sections -Wl,-Map=${CMAKE_BINARY_DIR}/${PROJECT_NAME}.map)

find_program(OBJCOPY arm-none-eabi-objcopy REQUIRED)
add_custom_command(TARGET ${PROJECT_NAME}.elf POST_BUILD
  COMMAND ${OBJCOPY} -O binary $<TARGET_FILE:${PROJECT_NAME}.elf> ${PROJECT_NAME}.bin
  COMMAND ${OBJCOPY} -O ihex   $<TARGET_FILE:${PROJECT_NAME}.elf> ${PROJECT_NAME}.hex
  COMMAND arm-none-eabi-size $<TARGET_FILE:${PROJECT_NAME}.elf>
  COMMENT "objcopy + size report"
  VERBATIM
)
"""

ARM_TOOLCHAIN = """\
# CMake toolchain file for bare-metal Cortex-M.
set(CMAKE_SYSTEM_NAME      Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

set(CMAKE_C_COMPILER   arm-none-eabi-gcc)
set(CMAKE_CXX_COMPILER arm-none-eabi-g++)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_AR           arm-none-eabi-gcc-ar)
set(CMAKE_RANLIB       arm-none-eabi-gcc-ranlib)

set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
"""

ARM_LD = """\
/* Linker script for @NAME@ — resize FLASH/RAM for your part from the datasheet. */
ENTRY(Reset_Handler)

MEMORY
{
  FLASH (rx)  : ORIGIN = @FLASH_ORIGIN@, LENGTH = @FLASH_SIZE@
  RAM   (rwx) : ORIGIN = @RAM_ORIGIN@,   LENGTH = @RAM_SIZE@
}

_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
  .text :
  {
    KEEP(*(.isr_vector))
    *(.text*)
    *(.rodata*)
    . = ALIGN(4);
    _etext = .;
  } > FLASH

  _sidata = LOADADDR(.data);

  .data :
  {
    . = ALIGN(4);
    _sdata = .;
    *(.data*)
    . = ALIGN(4);
    _edata = .;
  } > RAM AT > FLASH

  .bss (NOLOAD) :
  {
    . = ALIGN(4);
    _sbss = .;
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  } > RAM
}
"""

ARM_STARTUP = """\
/* Minimal Cortex-M startup: vector table, .data/.bss init, jump to main.
 * Written in C (no .S) so only project(@NAME@ C) is needed in CMake. */
#include <stdint.h>

extern uint32_t _estack, _sdata, _edata, _sidata, _sbss, _ebss;
int main(void);

void Reset_Handler(void);
__attribute__((weak)) void NMI_Handler(void)       { while (1) {} }
__attribute__((weak)) void HardFault_Handler(void) { while (1) {} }
__attribute__((weak)) void SVC_Handler(void)       {}
__attribute__((weak)) void PendSV_Handler(void)    {}
__attribute__((weak)) void SysTick_Handler(void)   {}

__attribute__((section(".isr_vector"), used))
static void (*const vectors[])(void) = {
    (void (*)(void))(&_estack),
    Reset_Handler,
    NMI_Handler,
    HardFault_Handler,
    0, 0, 0, 0, 0, 0, 0,
    SVC_Handler,
    0, 0,
    PendSV_Handler,
    SysTick_Handler,
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata) *dst++ = *src++;
    for (dst = &_sbss; dst < &_ebss; dst++) *dst = 0;
    (void)main();
    while (1) {}
}
"""

ARM_MAIN = """\
/*
 * @NAME@ — bare-metal Cortex-M skeleton (@CPU@).
 *
 * No vendor HAL, no startup assembly: see src/startup.c for the vector table.
 * `mcu build` produces .elf/.bin/.hex and a size report.
 */

#include <stdint.h>

/* Your part's peripheral header goes here, e.g. "samd21.h", "stm32f103xb.h". */

int main(void)
{
    for (;;) {
        /* ---------------------- YOUR CODE HERE ---------------------- */
    }
}
"""

ARM_DEBUG_JSON = """\
[
  {
    "label": "probe-rs: attach (run `probe-rs dap-server` first)",
    "adapter": "probe-rs",
    "request": "launch",
    "cwd": "$ZED_WORKTREE_ROOT",
    "server": "127.0.0.1:50000",
    "chip": "@CHIP@",
    "program-binary": "$ZED_WORKTREE_ROOT/build/@NAME@.elf",
    "coreConfigs": []
  },
  {
    "label": "pyOCD -> GDB: attach (run `pyocd gdbserver --persist` first)",
    "adapter": "GDB",
    "request": "attach",
    "target": "localhost:3333",
    "program": "$ZED_WORKTREE_ROOT/build/@NAME@.elf",
    "cwd": "$ZED_WORKTREE_ROOT"
  }
]
"""

# --------------------------------------------------------------------------
# AVR8X (megaAVR 0-series, tinyAVR 0/1/2-series) — same role, different core:
# PORT_t registers, per-pin port interrupts, USART0, UPDI, fuse0..fuse8.
# --------------------------------------------------------------------------

AVR8X_MAIN = """\
/*
 * @NAME@ — bare-metal AVR8X skeleton (avr-libc only, no Arduino core).
 *
 *   @LED_LABEL@ LED -> P@LED_PORT@@LED_BIT@
 *   @BTN_LABEL@ button -> P@BTN_PORT@@BTN_BIT@ : to GND, internal pull-up, pin interrupt
 *   TXD/RXD -> USART0 (UPDI sits on its own pin, PA0)
 *
 * `mcu build`, then flash over UPDI:
 *   mcu flash --method icsp --programmer atmelice_updi
 * simavr has no AVR8X core, so `mcu sim`/`board`/`debug`/`trace` are classic-AVR8
 * only — this part is bench-tested through the UART (`mcu monitor`) instead.
 * Everything above the marked block is plumbing; your firmware goes inside it.
 */

#ifndef F_CPU
#define F_CPU @FREQ@UL
#endif
#define UART_BAUD @BAUD@UL

#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdio.h>
#include <util/delay.h>

#define LED_PORT  PORT@LED_PORT@
#define LED_BIT   PIN@LED_BIT@_bm

#define BTN_PORT  PORT@BTN_PORT@
#define BTN_BIT   PIN@BTN_BIT@_bm

/* There is no UBRRn on AVR8X: the fractional baud generator takes
 * BAUD = 64 * f_CPU / (16 * baud), rounded (Microchip TB3216, 16x mode).
 * 16 MHz/115200 -> 556 (115107 Bd, -0.08 %), 20 MHz/115200 -> 694.
 * (The macro must not be called BAUD: `USART0.BAUD` is a register here.) */
#define BAUD_REG ((64UL * F_CPU + 8UL * UART_BAUD) / (16UL * UART_BAUD))

static int uart_putchar(char c, FILE *stream)
{
    (void)stream;
    if (c == '\\n') {
        uart_putchar('\\r', stream);
    }
    while (!(USART0.STATUS & USART_DREIF_bm)) {
    }
    USART0.TXDATAL = (uint8_t)c;
    return 0;
}
static FILE uart_stdout = FDEV_SETUP_STREAM(uart_putchar, NULL, _FDEV_SETUP_WRITE);

static void io_init(void)
{
    USART0.BAUD = (uint16_t)BAUD_REG;               /* 8N1, 16x oversampling */
    USART0.CTRLB = USART_TXEN_bm | USART_RXEN_bm;

    LED_PORT.DIRSET = LED_BIT;
    BTN_PORT.DIRCLR = BTN_BIT;
    BTN_PORT.PIN@BTN_BIT@CTRL = PORT_PULLUPEN_bm | PORT_ISC_FALLING_gc;
    sei();
}

/* The ISR only latches the event: printing from interrupt context is not safe,
 * and a polling loop would miss a short press. On AVR8X every pin has its own
 * interrupt, but the whole port still shares one vector. */
volatile uint8_t button_pressed;

ISR(PORT@BTN_PORT@_PORT_vect)
{
    if (!(BTN_PORT.IN & BTN_BIT)) {         /* pull-up high = released */
        button_pressed = 1;
    }
}

int main(void)
{
    io_init();

    for (;;) {
        /* ---------------------- YOUR CODE HERE ----------------------
         * Demo heartbeat, so the UART shows something before you write
         * yours: replace this whole block.
         */
        if (button_pressed) {
            button_pressed = 0;
            fprintf(&uart_stdout, "press\\n");
        }
        if (USART0.STATUS & USART_RXCIF_bm) {   /* demo: echo serial input */
            uart_putchar(USART0.RXDATAL, &uart_stdout);
            uart_putchar('\\n', &uart_stdout);
        }
        LED_PORT.OUTTGL = LED_BIT;
        fprintf(&uart_stdout, "tick\\n");
        _delay_ms(500);
        /* ---------------------- END OF DEMO ---------------------- */
    }
}
"""

AVR8X_README = """\
# @NAME@

Bare-metal AVR8X firmware (@MCU@, @FREQ@ Hz, avr-libc only — no Arduino core).

```sh
mcu build                                    # cmake + ninja -> build/@NAME@.elf/.hex/.bin
mcu size                                     # flash/RAM report
mcu fuses --programmer atmelice_updi         # fuse0..fuse8 (there is no lfuse/hfuse)
mcu flash --method icsp --programmer atmelice_updi   # UPDI, not ISP
mcu monitor                                  # serial console
```

Hardware map: LED on P@LED_PORT@@LED_BIT@ (@LED_LABEL@), button on P@BTN_PORT@@BTN_BIT@
(@BTN_LABEL@, internal pull-up, per-pin port interrupt), UART at @BAUD@ Bd on USART0.

No simulation: simavr emulates classic AVR8 only, so `mcu sim`, `board`, `debug` and
`trace` do not apply to this part — bench-test through the UART instead.
"""


GITIGNORE = """\
build/
sim/generated/
*.vcd
*.map
__pycache__/
"""


def _write(path: str, content: str, force=False):
    if os.path.exists(path) and not force:
        die(f"{path} exists — refusing to overwrite")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    info(f"  {os.path.relpath(path)}")


def create(dest: str, *, name=None, arch="avr", mcu="atmega328p", freq="16000000",
           led="PB5", button="PD2", baud=115200,
           cpu="cortex-m0plus", float_abi="-mfloat-abi=soft", chip=None,
           flash="256K", ram="32K", flash_origin="0x00000000",
           ram_origin="0x20000000", force=False):
    dest = os.path.abspath(dest)
    if os.path.isdir(dest) and os.listdir(dest) and not force:
        die(f"{dest} exists and is not empty")
    name = name or os.path.basename(os.path.normpath(dest))

    if arch == "avr":
        avr8x = is_avr8x(mcu)
        led_port, led_bit = parse_portpin(led, ports=avr8x_ports(mcu) if avr8x else None)
        btn_port, btn_bit = parse_portpin(button, ports=avr8x_ports(mcu) if avr8x else None)
        # AVR8X interrupts every pin individually (PORTx.PINnCTRL + one port
        # vector), so the classic PCINT group maths does not apply there.
        group, num = (None, None) if avr8x else pcint_for(btn_port, btn_bit)
        tok = dict(name=name, mcu=mcu, freq=freq, baud=baud,
                   led_port=led_port, led_bit=led_bit,
                   led_label=parse_label(led, led_port, led_bit),
                   btn_port=btn_port, btn_bit=btn_bit,
                   btn_label=parse_label(button, btn_port, btn_bit),
                   pcint_group=group, pcint_num=num)
        files = {
            "CMakeLists.txt": render(AVR_CMAKELISTS, **tok),
            "avr-gcc.cmake": AVR_TOOLCHAIN,
            "src/main.c": render(AVR8X_MAIN if is_avr8x(mcu) else AVR_MAIN, **tok),
        }
        readme = AVR8X_README if is_avr8x(mcu) else AVR_README
    elif arch == "arm":
        tok = dict(name=name, cpu=cpu, float_abi=float_abi,
                   ldscript=f"{name}.ld", chip=chip or "ATSAMD21J18A",
                   flash_size=flash, ram_size=ram,
                   flash_origin=flash_origin, ram_origin=ram_origin)
        files = {
            "CMakeLists.txt": render(ARM_CMAKELISTS, **tok),
            "arm-gcc.cmake": ARM_TOOLCHAIN,
            f"{name}.ld": render(ARM_LD, **tok),
            "src/startup.c": render(ARM_STARTUP, **tok),
            "src/main.c": render(ARM_MAIN, **tok),
            ".zed/debug.json": render(ARM_DEBUG_JSON, **tok),
        }
        readme = ARM_README
    else:
        die(f"unknown arch '{arch}' (use avr or arm)")

    files["README.md"] = render(readme, **tok)
    files[".gitignore"] = GITIGNORE

    for rel, content in files.items():
        _write(os.path.join(dest, rel), content, force=force)

    ok(f"created {dest} ({arch})")
    info(f"     next: cd {dest} && mcu build")
    return 0


AVR_README = """\
# @NAME@

Bare-metal AVR firmware (@MCU@, @FREQ@ Hz, avr-libc only — no Arduino core).

```sh
mcu build      # cmake + ninja -> build/@NAME@.elf/.hex/.bin/.map
mcu size       # flash/RAM report
mcu flash      # USB bootloader (--method icsp for a programmer)
mcu monitor    # serial console
mcu sim        # run under simavr
mcu board --led @LED_LABEL@ --button @BTN_LABEL@ --press 1.5s:150ms --seconds 8
mcu debug      # breakpoints/stepping against simavr
mcu trace      # VCD I/O trace
```

Hardware map: LED on P@LED_PORT@@LED_BIT@ (@LED_LABEL@), button on P@BTN_PORT@@BTN_BIT@
(@BTN_LABEL@, internal pull-up, PCINT@PCINT_NUM@ interrupt), UART at @BAUD@ Bd on PD0/PD1.
"""

ARM_README = """\
# @NAME@

Bare-metal Cortex-M firmware (@CPU@), no vendor HAL.

```sh
mcu build      # cmake + ninja -> build/@NAME@.elf/.bin/.hex + size report
mcu size
mcu flash      # pyocd (auto-detects a CMSIS-DAP probe)
mcu monitor    # serial console
mcu debug --hw # pyocd gdbserver + arm-none-eabi-gdb against a real probe
```

- `@NAME@.ld` — resize FLASH/RAM for your part (`@FLASH_SIZE@`/`@RAM_SIZE@` by default).
- `.zed/debug.json` — debugger configs for Zed (probe-rs / pyOCD chip `@CHIP@`).
- There is no AVR-style simulation for Cortex-M here; flashing/debugging needs a probe.
"""
