"""End-to-end tests: scaffold -> configure -> compile -> run.

Each test skips itself when the toolchain it needs is missing, so the suite is
useful on a bare container and exhaustive on a machine with the full toolchain.
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, SRC)

from mcu import scaffold  # noqa: E402

HAVE = {t: shutil.which(t) for t in
        ("cmake", "ninja", "avr-gcc", "avr-size", "arm-none-eabi-gcc",
         "arm-none-eabi-objdump", "avr-objcopy", "simavr", "avr-gdb")}
SIMAVR_PREFIX = os.environ.get("SIMAVR_PREFIX", "/usr/local")
HAVE_HEADERS = os.path.isdir(os.path.join(SIMAVR_PREFIX, "include", "simavr", "parts"))
ENV = {**os.environ, "PYTHONPATH": SRC}


@contextlib.contextmanager
def quiet():
    """Swallow command output so test logs stay readable."""
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        yield


def build(dest):
    """Run `mcu build` as a subprocess, returning (rc, combined output).

    A subprocess (not redirect_stdout) because cmake/avr-gcc write to the
    inherited file descriptor — redirecting only Python-level output would hide
    the compiler error exactly when it matters.
    """
    r = subprocess.run([sys.executable, "-m", "mcu", "-C", dest, "build"],
                       capture_output=True, text=True, timeout=300, env=ENV)
    return r.returncode, r.stdout + r.stderr


def mcu(*argv, timeout=180):
    """Run `mcu ...` as a real subprocess (needed when output comes from a child
    process, which redirect_stdout cannot capture)."""
    return subprocess.run([sys.executable, "-m", "mcu", *argv],
                          capture_output=True, text=True, timeout=timeout, env=ENV)


@unittest.skipUnless(all(HAVE[t] for t in ("cmake", "ninja", "avr-gcc", "avr-objcopy")),
                     "needs cmake, ninja, avr-gcc and avr-objcopy")
class TestAvrBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "blinky")
        with quiet():
            scaffold.create(self.dest, name="blinky", arch="avr",
                            led="D13", button="D2")

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_elf_hex_and_bin(self):
        rc, out = build(self.dest)
        self.assertEqual(rc, 0, out)
        builddir = os.path.join(self.dest, "build")
        for name in ("blinky.elf", "blinky.hex", "blinky.bin", "blinky.map"):
            self.assertTrue(os.path.isfile(os.path.join(builddir, name)),
                            f"{name} missing\n{out}")

    def test_hex_is_intel_hex(self):
        build(self.dest)
        with open(os.path.join(self.dest, "build", "blinky.hex")) as fh:
            first = fh.readline()
        self.assertTrue(first.startswith(":"), first)

    def test_size_report_runs(self):
        build(self.dest)
        r = mcu("-C", self.dest, "size", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Program:", r.stdout)

    def test_clean_removes_build(self):
        build(self.dest)
        r = mcu("-C", self.dest, "clean", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.isdir(os.path.join(self.dest, "build")))

    @unittest.skipUnless(all(HAVE[t] for t in ("simavr", "avr-gdb")) and HAVE_HEADERS,
                         "needs simavr + avr-gdb + simavr headers")
    def test_simulation_runs_and_talks(self):
        build(self.dest)
        r = mcu("-C", self.dest, "sim", "--seconds", "2")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("tick", r.stdout + r.stderr)

    @unittest.skipUnless(HAVE["simavr"] and HAVE_HEADERS, "needs simavr + headers")
    def test_board_harness_runs_with_peripherals(self):
        build(self.dest)
        r = mcu("-C", self.dest, "board", "--led", "D13", "--button", "D2",
                "--press", "1s:150ms", "--seconds", "3", timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        combined = r.stdout + r.stderr
        self.assertIn("[led", combined)
        self.assertIn("[button", combined)
        self.assertIn("led edge(s)", combined)


@unittest.skipUnless(all(HAVE[t] for t in ("cmake", "ninja", "arm-none-eabi-gcc",
                                           "arm-none-eabi-objdump")),
                     "needs cmake, ninja and arm-none-eabi-gcc")
class TestArmBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "skeleton")
        with quiet():
            scaffold.create(self.dest, name="skeleton", arch="arm")

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_elf_for_cortex_m(self):
        rc, out = build(self.dest)
        self.assertEqual(rc, 0, out)
        elf = os.path.join(self.dest, "build", "skeleton.elf")
        self.assertTrue(os.path.isfile(elf), out)

    def test_reset_vector_is_at_address_zero(self):
        """The vector table is KEEP()'d as the first thing in .text, so word 0
        must be the initial stack pointer and word 1 the Thumb Reset_Handler."""
        build(self.dest)
        binp = os.path.join(self.dest, "build", "skeleton.bin")
        with open(binp, "rb") as fh:
            head = fh.read(8)
        sp = int.from_bytes(head[0:4], "little")
        reset = int.from_bytes(head[4:8], "little")
        self.assertEqual(sp, 0x20008000, f"initial SP is 0x{sp:08x}")   # 32K RAM
        self.assertTrue(reset & 1, f"Reset_Handler 0x{reset:08x} lacks the Thumb bit")
        self.assertLess(reset, 0x40000, "Reset_Handler should live in flash")

    def test_size_and_clean(self):
        build(self.dest)
        r = mcu("-C", self.dest, "size", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = mcu("-C", self.dest, "clean", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.isdir(os.path.join(self.dest, "build")))


if __name__ == "__main__":
    unittest.main()
