"""Parsers and small helpers."""

import os
import sys
import tempfile
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


class TestSimavrCaps(unittest.TestCase):
    """`mcu debug`/`trace` must know which optional simavr flags exist.

    simavr has no --version, so the probe is behavioural: hand it the flag, a
    value and a firmware that cannot exist, and see which name it complains
    about. Debian's simavr 1.6 ignores unknown flags and then tries to load the
    VALUE as the firmware; a modern build fails on the firmware path instead.
    """

    def _fake_simavr(self, legacy: bool) -> str:
        d = tempfile.mkdtemp()
        path = os.path.join(d, "simavr")
        # $1 = flag, $2 = the flag's value, $3 = the firmware
        idx = "$2" if legacy else "$3"
        with open(path, "w") as fh:
            fh.write(f"#!/bin/sh\necho \"could not read {idx}\" >&2\nexit 1\n")
        os.chmod(path, 0o755)
        return path

    def setUp(self):
        util._simavr_cache.clear()
        self._env = os.environ.pop("MCU_SIMAVR_FLAGS", None)

    def tearDown(self):
        util._simavr_cache.clear()
        if self._env is not None:
            os.environ["MCU_SIMAVR_FLAGS"] = self._env
        else:
            os.environ.pop("MCU_SIMAVR_FLAGS", None)

    def test_modern_build_accepts_every_flag(self):
        caps = util.simavr_caps(self._fake_simavr(legacy=False))
        self.assertEqual(caps, {"gdb_port", "signal", "output"})

    def test_legacy_build_reports_nothing(self):
        self.assertEqual(util.simavr_caps(self._fake_simavr(legacy=True)), set())

    def test_env_override_wins(self):
        os.environ["MCU_SIMAVR_FLAGS"] = "gdb_port, signal"
        self.assertEqual(util.simavr_caps("/nonexistent/simavr"),
                         {"gdb_port", "signal"})

    def test_note_mentions_the_missing_traces(self):
        self.assertIn("-at", util.simavr_note(set()))
        self.assertIn("ok", util.simavr_note({"gdb_port", "signal", "output"}))


class TestRunStdoutPath(unittest.TestCase):
    def test_stdout_is_redirected_to_a_file(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "captured.txt")
        util.run(["echo", "vcd-ish"], check=False, stdout_path=out)
        with open(out) as fh:
            self.assertEqual(fh.read().strip(), "vcd-ish")

    def test_dry_run_only_previews(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "never.txt")
        util.run(["echo", "hi"], dry=True, stdout_path=out)
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
