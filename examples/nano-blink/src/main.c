/*
 * nano_blink — bare-metal AVR skeleton (avr-libc only, no Arduino core).
 *
 *   D13 LED -> PB5
 *   D2 button -> PD2 : to GND, internal pull-up, PCINT
 *   TXD -> PD1, RXD -> PD0 : UART, 115200 Bd
 *
 * `mcu build`, simulate with `mcu board --led D13 --button D2`.
 * Everything above the marked block is the plumbing the CLI and the generated
 * board harness rely on; your firmware goes inside the block in main().
 */

#ifndef F_CPU
#define F_CPU 16000000UL
#endif
#define BAUD 115200UL

#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdio.h>
#include <util/delay.h>

#define LED_PORT  PORTB
#define LED_DDR   DDRB
#define LED_BIT   5

#define BTN_PORT  PORTD
#define BTN_PIN   PIND
#define BTN_DDR   DDRD
#define BTN_BIT   2

/* Double-speed (U2X) divisor: UBRR = F_CPU / (8 * BAUD) - 1.
 * 16 MHz/115200 -> 117647 Bd, +2.1 % (single speed would be -3.5 %). */
#define UBRR_VAL ((F_CPU / (8UL * BAUD)) - 1UL)

static int uart_putchar(char c, FILE *stream)
{
    (void)stream;
    if (c == '\n') {
        uart_putchar('\r', stream);
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
    PCMSK2 |= _BV(PCINT18);
    PCICR |= _BV(PCIE2);
    sei();
}

/* The ISR only latches the event: printing from interrupt context is not safe,
 * and a polling loop would miss a short press. */
volatile uint8_t button_pressed;

ISR(PCINT2_vect)
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
            fprintf(&uart_stdout, "press\n");
        }
        if (UCSR0A & _BV(RXC0)) {            /* demo: echo serial input */
            uart_putchar(UDR0, &uart_stdout);
            uart_putchar('\n', &uart_stdout);
        }
        LED_PORT ^= _BV(LED_BIT);
        fprintf(&uart_stdout, "tick\n");
        _delay_ms(500);
        /* ---------------------- END OF DEMO ---------------------- */
    }
}
