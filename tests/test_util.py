"""Parsers and small helpers."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcu import util  # noqa: E402


class TestDurations(unittest.TestCase):
    def test_bare_number_is_milliseconds(self):
        self.assertEqual(util.parse_ms("500"), 500)
        self.assertEqual(util.parse_ms(500), 500)
        self.assertEqual(util.parse_ms("1.5"), 1.5)

    def test_units(self):
        self.assertEqual(util.parse_ms("150ms"), 150)
        self.assertEqual(util.parse_ms("1.5s"), 1500)
        self.assertEqual(util.parse_ms("2m"), 120000)
        self.assertEqual(util.parse_ms(" 250 ms "), 250)

    def test_garbage_dies(self):
        with self.assertRaises(SystemExit):
            util.parse_ms("soon")


class TestPortPins(unittest.TestCase):
    def test_arduino_labels(self):
        self.assertEqual(util.parse_portpin("D13"), ("B", 5))
        self.assertEqual(util.parse_portpin("D2"), ("D", 2))
        self.assertEqual(util.parse_portpin("D8"), ("B", 0))
        self.assertEqual(util.parse_portpin("A0"), ("C", 0))
        self.assertEqual(util.parse_portpin("a3"), ("C", 3))

    def test_explicit_forms(self):
        self.assertEqual(util.parse_portpin("PB5"), ("B", 5))
        self.assertEqual(util.parse_portpin("b5"), ("B", 5))
        self.assertEqual(util.parse_portpin("PB:5"), ("B", 5))
        self.assertEqual(util.parse_portpin("D5"), ("D", 5))

    def test_d5_is_not_a_label(self):
        # D5 exists both ways; the Arduino label wins and both agree here
        self.assertEqual(util.parse_portpin("D5"), util.ARDUINO_LABELS["D5"])

    def test_bad_pin_dies(self):
        for bad in ("ZZ9", "", "PZ1", "D99"):
            with self.assertRaises(SystemExit):
                util.parse_portpin(bad)

    def test_labels(self):
        self.assertEqual(util.parse_label("D13", "B", 5), "D13")
        self.assertEqual(util.parse_label("pb0", "B", 0), "PB0")


class TestPcint(unittest.TestCase):
    def test_groups(self):
        self.assertEqual(util.pcint_for("B", 0), (0, 0))
        self.assertEqual(util.pcint_for("B", 5), (0, 5))
        self.assertEqual(util.pcint_for("C", 0), (1, 8))
        self.assertEqual(util.pcint_for("D", 2), (2, 18))
        self.assertEqual(util.pcint_for("D", 7), (2, 23))

    def test_no_pcint_on_a_port_a(self):
        with self.assertRaises(SystemExit):
            util.pcint_for("A", 0)


class TestMisc(unittest.TestCase):
    def test_c_string(self):
        self.assertEqual(util.c_string('a"b'), '"a\\"b"')
        self.assertEqual(util.c_string("a\\b"), '"a\\\\b"')

    def test_human_ms(self):
        self.assertEqual(util.human_ms(250), "250.0 ms")
        self.assertEqual(util.human_ms(1500), "1.50 s")

    def test_serial_ports_never_raises(self):
        self.assertIsInstance(util.serial_ports(), list)

    def test_install_hint_is_a_string(self):
        self.assertIsInstance(util.install_hint("avr-gcc"), str)


if __name__ == "__main__":
    unittest.main()
