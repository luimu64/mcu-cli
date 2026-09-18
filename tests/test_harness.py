"""Harness generation: config arrays, port de-duplication, compile (when possible)."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcu import harness  # noqa: E402
from mcu.project import Project  # noqa: E402

SIMAVR_PREFIX = os.environ.get("SIMAVR_PREFIX", "/usr/local")
HAVE_SIMAVR = os.path.isdir(os.path.join(SIMAVR_PREFIX, "include", "simavr", "parts"))


def make_project(root, name="fw"):
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    with open(os.path.join(root, "CMakeLists.txt"), "w") as fh:
        fh.write('cmake_minimum_required(VERSION 3.20)\n'
                 'set(MCU   "atmega328p" CACHE STRING "")\n'
                 'set(F_CPU "16000000" CACHE STRING "")\n'
                 f'project({name} C)\n')
    os.makedirs(os.path.join(root, "build"), exist_ok=True)
    open(os.path.join(root, "build", f"{name}.elf"), "w").close()
    return Project(root)


class TestRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = make_project(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_led_and_button_entries(self):
        p = harness.Peripherals(leds=[("B", 5, "D13"), ("B", 0, "D8")],
                                buttons=[("D", 2)])
        src = harness.render(self.proj, p)
        self.assertIn("{ 'B', 5, \"D13\" }", src)
        self.assertIn("{ 'B', 0, \"D8\" }", src)
        self.assertIn("{ 'D', 2 },", src)
        self.assertIn("#define N_LEDS    2", src)
        self.assertIn("#define N_BUTTONS 1", src)

    def test_mcu_and_clock_are_baked_in(self):
        src = harness.render(self.proj, harness.Peripherals())
        self.assertIn('strcpy(f.mmcu, "atmega328p")', src)
        self.assertIn("f.frequency = 16000000", src)

    def test_defaults_are_valid_c_when_empty(self):
        src = harness.render(self.proj, harness.Peripherals())
        self.assertIn("#define N_LEDS    0", src)
        self.assertIn("{ 0, 0, 0 },", src)

    def test_press_and_rx_schedules(self):
        p = harness.Peripherals(buttons=[("D", 2)],
                                presses=[(0, 1500, 150)],
                                rx=[(1200, "abc")])
        src = harness.render(self.proj, p)
        self.assertIn("{ 0, 1500, 150 },", src)
        self.assertIn('{ 1200, "abc" },', src)

    def test_rx_text_is_escaped(self):
        p = harness.Peripherals(rx=[(10, 'a"b')])
        self.assertIn('\\"b', harness.render(self.proj, p))

    def test_uart_and_keys_flags(self):
        self.assertIn("use_uart = 0", harness.render(
            self.proj, harness.Peripherals(), uart=False))
        self.assertIn("use_keys = 1", harness.render(
            self.proj, harness.Peripherals(), keys=True))

    def test_firmware_path_is_the_project_elf(self):
        src = harness.render(self.proj, harness.Peripherals())
        self.assertIn(self.proj.elf, src)


@unittest.skipUnless(HAVE_SIMAVR and shutil.which("cc"),
                     f"needs simavr headers ({SIMAVR_PREFIX}) and a host cc")
class TestCompile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = make_project(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_harness_compiles(self):
        p = harness.Peripherals(leds=[("B", 5, "D13")], buttons=[("D", 2)])
        binary = harness.build(self.proj, p, prefix=SIMAVR_PREFIX)
        self.assertTrue(os.path.isfile(binary))
        self.assertTrue(os.access(binary, os.X_OK))
        # it should at least print usage-ish errors rather than crash on load
        rc = subprocess.run([binary], capture_output=True, text=True,
                            timeout=30, input="q")
        self.assertIn(rc.returncode, (0, 1))

    def test_regeneration_is_idempotent(self):
        p = harness.Peripherals(leds=[("B", 5, "D13")])
        first = harness.build(self.proj, p, prefix=SIMAVR_PREFIX)
        src = os.path.join(harness.generated_dir(self.proj), "board.c")
        mtime = os.path.getmtime(src)
        second = harness.build(self.proj, p, prefix=SIMAVR_PREFIX)
        self.assertEqual(first, second)
        self.assertEqual(mtime, os.path.getmtime(src))   # unchanged source untouched


if __name__ == "__main__":
    unittest.main()
