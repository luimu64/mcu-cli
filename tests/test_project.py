"""Project discovery: arch, MCU, clock, outputs, upward search."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcu.project import Project  # noqa: E402

AVR_CMAKE = """\
cmake_minimum_required(VERSION 3.20)
set(MCU   "atmega328p" CACHE STRING "part")
set(F_CPU "16000000" CACHE STRING "clock")
project(blinky C)
"""

ARM_CMAKE = """\
cmake_minimum_required(VERSION 3.20)
set(CPU_FLAGS -mcpu=cortex-m4 -mthumb)
project(motor C)
"""


class TestProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _mk(self, body, name="CMakeLists.txt", sub=""):
        d = os.path.join(self.root, sub) if sub else self.root
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as fh:
            fh.write(body)
        return d

    def test_avr_facts(self):
        self._mk(AVR_CMAKE)
        p = Project(self.root)
        self.assertEqual(p.arch, "avr")
        self.assertEqual(p.name, "blinky")
        self.assertEqual(p.mcu, "atmega328p")
        self.assertEqual(p.freq, "16000000")
        self.assertEqual(p.toolchain_file(), "avr-gcc.cmake")

    def test_arm_facts(self):
        self._mk(ARM_CMAKE)
        p = Project(self.root)
        self.assertEqual(p.arch, "arm")
        self.assertEqual(p.name, "motor")
        self.assertEqual(p.mcu, "cortex-m4")          # from -mcpu
        self.assertEqual(p.toolchain_file(), "arm-gcc.cmake")

    def test_cache_wins_over_cmakelists(self):
        d = self._mk(AVR_CMAKE)
        os.makedirs(os.path.join(d, "build"))
        with open(os.path.join(d, "build", "CMakeCache.txt"), "w") as fh:
            fh.write("MCU:STRING=atmega2560\nF_CPU:STRING=8000000\n")
        p = Project(d)
        self.assertEqual(p.mcu, "atmega2560")
        self.assertEqual(p.freq, "8000000")

    def test_finds_project_upwards(self):
        d = self._mk(AVR_CMAKE)
        deep = os.path.join(d, "src", "nested")
        os.makedirs(deep)
        self.assertEqual(Project.find(deep).dir, os.path.abspath(d))

    def test_no_project_dies(self):
        with self.assertRaises(SystemExit):
            Project.find(self.root)          # empty dir tree without CMakeLists

    def test_output_discovery(self):
        d = self._mk(AVR_CMAKE)
        os.makedirs(os.path.join(d, "build"))
        open(os.path.join(d, "build", "blinky.elf"), "w").close()
        open(os.path.join(d, "build", "blinky.hex"), "w").close()
        p = Project(d)
        self.assertTrue(p.elf.endswith("blinky.elf"))
        self.assertTrue(p.hex.endswith("blinky.hex"))
        self.assertTrue(p.configured() is False)

    def test_configure_cmd(self):
        self._mk(AVR_CMAKE)
        cmd = Project(self.root).configure_cmd("Debug")
        self.assertIn("-DCMAKE_TOOLCHAIN_FILE=avr-gcc.cmake", cmd)
        self.assertIn("-DCMAKE_BUILD_TYPE=Debug", cmd)


if __name__ == "__main__":
    unittest.main()
