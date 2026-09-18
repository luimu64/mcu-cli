/*
 * nano_blink — bare-metal AVR (avr-libc only, no Arduino core).
 *
 *   D13 LED -> PB5
 *   TXD -> PD1, RXD -> PD0 : UART, 115200 Bd
 *   D2 button -> PD2 : to GND, internal pull-up, PCINT
 *
 * Build with `mcu build`, simulate with `mcu board --led D13 --button D2`.
 */

#ifndef F_CPU
#define F_CPU 16000000UL
#endif

#ifndef __AVR_ATmega328P__
/* The demo targets the ATmega328P; delete this guard for other parts. */
#endif

#define BAUD 115200UL

#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>
#include <stdio.h>
#include <ctype.h>

#define LED_PORT  PORTB
#define LED_DDR   DDRB
#define LED_BIT   5

#define BTN_PORT  PORTD
#define BTN_PIN   PIND
#define BTN_DDR   DDRD
#define BTN_BIT   2

/* Double-speed (U2X) divisor: UBRR = F_CPU / (8 * BAUD) - 1.
 * At 16 MHz/115200 that is 16 -> 117647 Bd, +2.1 % (same as the Arduino core).
 * Single speed would need UBRR 8 -> 111111 Bd, -3.5 %: out of spec. */
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

static void uart_init(void)
{
    UBRR0H = (uint8_t)(UBRR_VAL >> 8);
    UBRR0L = (uint8_t)(UBRR_VAL & 0xFF);
    UCSR0A = _BV(U2X0);
    UCSR0B = _BV(TXEN0) | _BV(RXEN0);
    UCSR0C = _BV(UCSZ01) | _BV(UCSZ00);      /* 8 data bits, no parity, 1 stop */
}

/* The ISR only latches state: printing from interrupt context is not safe and a
 * polling loop would miss a short press. */
volatile uint8_t blink_enabled = 1;
volatile uint8_t button_events;

ISR(PCINT2_vect)
{
    if (BTN_PIN & _BV(BTN_BIT)) {
        return;                              /* pull-up high = released */
    }
    blink_enabled = !blink_enabled;
    button_events++;
}

static void button_init(void)
{
    BTN_DDR &= (uint8_t)~_BV(BTN_BIT);
    BTN_PORT |= _BV(BTN_BIT);                /* internal pull-up */
    PCMSK2 |= _BV(PCINT18);
    PCICR |= _BV(PCIE2);
    sei();
}

int main(void)
{
    uart_init();
    LED_DDR |= _BV(LED_BIT);
    button_init();

    fprintf(&uart_stdout, "\nnano_blink up: %lu Hz\n", (unsigned long)F_CPU);

    uint8_t led_on = 0;
    uint16_t seconds = 0;

    for (;;) {
        if (button_events) {
            button_events = 0;
            fprintf(&uart_stdout, "button: heartbeat %s\n",
                    blink_enabled ? "resumed" : "paused");
        }

        led_on = blink_enabled ? !led_on : 0;
        if (led_on) {
            LED_PORT |= _BV(LED_BIT);
            fprintf(&uart_stdout, "tick %u\n", seconds++);
        } else {
            LED_PORT &= (uint8_t)~_BV(LED_BIT);
        }

        if (UCSR0A & _BV(RXC0)) {             /* echo serial input, upper-cased */
            char c = (char)UDR0;
            uart_putchar(toupper((unsigned char)c), &uart_stdout);
            uart_putchar('\n', &uart_stdout);
        }
        _delay_ms(500);
    }
}
