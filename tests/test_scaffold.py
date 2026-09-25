"""Scaffolding: files created, tokens substituted, generated code consistent."""

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcu import scaffold  # noqa: E402



@contextlib.contextmanager
def quiet():
    """Swallow command output so test logs stay readable."""
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        yield


class TestAvrScaffold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "blinky")
        with quiet():
            scaffold.create(self.dest, name="blinky", arch="avr",
                            mcu="atmega328p", freq="16000000",
                            led="D13", button="D2")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, rel):
        with open(os.path.join(self.dest, rel)) as fh:
            return fh.read()

    def test_files_exist(self):
        for rel in ("CMakeLists.txt", "avr-gcc.cmake", "src/main.c",
                    "README.md", ".gitignore"):
            self.assertTrue(os.path.isfile(os.path.join(self.dest, rel)), rel)

    def test_no_unsubstituted_tokens(self):
        for rel in ("CMakeLists.txt", "src/main.c", "README.md"):
            self.assertNotIn("@", self.read(rel), f"token left in {rel}")

    def test_pcint_derived_from_the_button_pin(self):
        src = self.read("src/main.c")
        self.assertIn("ISR(PCINT2_vect)", src)      # PD2 -> group 2
        self.assertIn("PCMSK2 |= _BV(PCINT18)", src)
        self.assertIn("PCICR |= _BV(PCIE2)", src)
        self.assertIn("#define BTN_BIT   2", src)
        self.assertIn("#define BTN_PORT  PORTD", src)

    def test_led_pins_from_labels(self):
        src = self.read("src/main.c")
        self.assertIn("#define LED_PORT  PORTB", src)   # D13 -> PB5
        self.assertIn("#define LED_BIT   5", src)

    def test_main_marks_the_replaceable_block(self):
        """The scaffold is plumbing + one marked demo block: keep it short and
        keep the marker greppable, or the generated code stops being a template."""
        src = self.read("src/main.c")
        self.assertEqual(src.count("YOUR CODE HERE"), 1)
        self.assertLess(len(src.splitlines()), 100)

    def test_clock_and_baud_reach_the_code(self):
        src = self.read("src/main.c")
        self.assertIn("F_CPU 16000000UL", src)
        self.assertIn("BAUD 115200UL", src)

    def test_button_on_port_b_uses_group_0(self):
        dest = os.path.join(self.tmp.name, "b0")
        with quiet():
            scaffold.create(dest, name="b0", arch="avr", button="D8")   # PB0
        with open(os.path.join(dest, "src/main.c")) as fh:
            src = fh.read()
        self.assertIn("ISR(PCINT0_vect)", src)
        self.assertIn("_BV(PCINT0)", src)

    def test_refuses_non_empty_dir(self):
        with self.assertRaises(SystemExit), quiet():
            scaffold.create(self.dest, name="blinky")

    def test_other_mcu_and_clock(self):
        dest = os.path.join(self.tmp.name, "mega")
        with quiet():
            scaffold.create(dest, name="mega", arch="avr",
                            mcu="atmega2560", freq="14745600")
        with open(os.path.join(dest, "CMakeLists.txt")) as fh:
            cmake = fh.read()
        self.assertIn('set(MCU   "atmega2560"', cmake)
        self.assertIn('set(F_CPU "14745600"', cmake)


class TestAvr8xScaffold(unittest.TestCase):
    """`mcu new --mcu atmega4809` must emit AVR8X code, not classic AVR8 code:
    PORT_t registers, per-pin port interrupts, USART0, and a README that says
    UPDI instead of ISP."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "nano_every")
        with quiet():
            scaffold.create(self.dest, name="nano_every", arch="avr",
                            mcu="atmega4809", freq="20000000",
                            led="PB5", button="PD2")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, rel):
        with open(os.path.join(self.dest, rel)) as fh:
            return fh.read()

    def test_no_unsubstituted_tokens(self):
        for rel in ("CMakeLists.txt", "src/main.c", "README.md"):
            self.assertNotIn("@", self.read(rel), f"token left in {rel}")

    def test_port_t_register_model(self):
        src = self.read("src/main.c")
        self.assertIn("#define LED_PORT  PORTB", src)
        self.assertIn("#define LED_BIT   PIN5_bm", src)
        self.assertIn("#define BTN_PORT  PORTD", src)
        self.assertIn("#define BTN_BIT   PIN2_bm", src)
        self.assertIn("LED_PORT.DIRSET = LED_BIT", src)
        self.assertIn("LED_PORT.OUTTGL = LED_BIT", src)
        self.assertIn("BTN_PORT.PIN2CTRL = PORT_PULLUPEN_bm | PORT_ISC_FALLING_gc",
                      src)

    def test_per_pin_interrupt_on_the_port_vector(self):
        src = self.read("src/main.c")
        self.assertIn("ISR(PORTD_PORT_vect)", src)
        self.assertIn("if (!(BTN_PORT.IN & BTN_BIT))", src)
        self.assertNotIn("PCMSK", src)               # that is classic AVR8

    def test_usart0_and_no_ubrr(self):
        src = self.read("src/main.c")
        self.assertIn("USART0.BAUD = (uint16_t)BAUD_REG", src)
        self.assertIn("USART0.CTRLB = USART_TXEN_bm | USART_RXEN_bm", src)
        self.assertIn("USART0.TXDATAL = (uint8_t)c", src)
        self.assertIn("USART0.RXDATAL", src)
        self.assertNotIn("UCSR0A", src)
        self.assertNotIn("UBRR0", src)                # the comment may say "no UBRRn"
        # the macro must not be named BAUD: `USART0.BAUD` is a register here
        self.assertNotIn("#define BAUD ", src)

    def test_baud_math_matches_the_header_formula(self):
        src = self.read("src/main.c")
        self.assertIn("#define UART_BAUD 115200UL", src)
        self.assertIn("#define BAUD_REG ((64UL * F_CPU + 8UL * UART_BAUD) / "
                      "(16UL * UART_BAUD))", src)
        reg = (64 * 20_000_000 + 8 * 115200) // (16 * 115200)
        self.assertEqual(reg, 694)                   # 20 MHz -> 694 (115273 Bd)
        self.assertEqual((64 * 16_000_000 + 8 * 115200) // (16 * 115200), 556)

    def test_main_marks_the_replaceable_block(self):
        src = self.read("src/main.c")
        self.assertEqual(src.count("YOUR CODE HERE"), 1)
        self.assertLess(len(src.splitlines()), 100)

    def test_readme_talks_udpi_and_no_simulation(self):
        md = self.read("README.md")
        self.assertIn("atmelice_updi", md)
        self.assertIn("UPDI, not ISP", md)
        self.assertIn("No simulation", md)
        self.assertNotIn("mcu board --led", md)      # no sim -> no board harness

    def test_tinyavr_also_gets_the_avr8x_template(self):
        dest = os.path.join(self.tmp.name, "tiny")
        with quiet():
            scaffold.create(dest, name="tiny", arch="avr", mcu="attiny1616",
                            freq="16000000", led="PB5", button="PA2")
        with open(os.path.join(dest, "src/main.c")) as fh:
            src = fh.read()
        self.assertIn("ISR(PORTA_PORT_vect)", src)
        self.assertIn("USART0.BAUD", src)

    def test_classic_parts_keep_the_classic_template(self):
        dest = os.path.join(self.tmp.name, "uno")
        with quiet():
            scaffold.create(dest, name="uno", arch="avr", mcu="atmega328p")
        with open(os.path.join(dest, "src/main.c")) as fh:
            src = fh.read()
        self.assertIn("ISR(PCINT2_vect)", src)
        self.assertIn("UCSR0A", src)

    def test_atmega2560_is_not_avr8x(self):
        dest = os.path.join(self.tmp.name, "mega")
        with quiet():
            scaffold.create(dest, name="mega", arch="avr", mcu="atmega2560",
                            freq="14745600")
        with open(os.path.join(dest, "src/main.c")) as fh:
            src = fh.read()
        self.assertNotIn("PORTB.DIRSET", src)
        self.assertIn("UBRR0H", src)                  # classic USART, not USART0


class TestArmScaffold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "samd")
        with quiet():
            scaffold.create(self.dest, name="samd", arch="arm",
                            cpu="cortex-m0plus", chip="ATSAMD21J18A",
                            flash="256K", ram="32K")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, rel):
        with open(os.path.join(self.dest, rel)) as fh:
            return fh.read()

    def test_files(self):
        for rel in ("CMakeLists.txt", "arm-gcc.cmake", "samd.ld",
                    "src/startup.c", "src/main.c", ".zed/debug.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.dest, rel)), rel)

    def test_linker_sizes_and_cpu(self):
        self.assertIn("LENGTH = 256K", self.read("samd.ld"))
        self.assertIn("LENGTH = 32K", self.read("samd.ld"))
        self.assertIn("-mcpu=cortex-m0plus", self.read("CMakeLists.txt"))

    def test_vector_table_present(self):
        self.assertIn(".isr_vector", self.read("src/startup.c"))
        self.assertIn("Reset_Handler", self.read("src/startup.c"))

    def test_debug_json_is_valid_and_named(self):
        import json
        data = json.loads(self.read(".zed/debug.json"))
        self.assertIsInstance(data, list)
        self.assertIn("ATSAMD21J18A", json.dumps(data))
        self.assertTrue(any("samd.elf" in entry.get("program", "")
                            or "samd.elf" in entry.get("program-binary", "")
                            for entry in data))

    def test_main_is_a_marked_skeleton(self):
        src = self.read("src/main.c")
        self.assertEqual(src.count("YOUR CODE HERE"), 1)
        self.assertLess(len(src.splitlines()), 25)

    def test_no_tokens_left(self):
        for rel in ("CMakeLists.txt", "samd.ld", "src/main.c", "README.md"):
            self.assertNotIn("@", self.read(rel), rel)


if __name__ == "__main__":
    unittest.main()
