"""`mcu fuses` — the DWEN (debugWIRE) path, driven by a stub avrdude.

No hardware here, so the stub plays the chip: it logs the argv it was given and
answers fuse reads from the environment. That is enough to pin the argv, the
bit math and the refusals, which is where the mistakes live.
"""

import contextlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, SRC)

from mcu import scaffold  # noqa: E402


@contextlib.contextmanager
def quiet():
    """Swallow command output so test logs stay readable."""
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        yield

STUB = '''#!/usr/bin/env python3
"""Fake avrdude: log the argv, answer fuse reads, optionally fail once."""
import os
import sys

args = sys.argv[1:]
log = os.environ.get("FAKE_AVRDUDE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(" ".join(args) + "\\n")

fail_once = os.environ.get("FAKE_FAIL_ONCE")
if fail_once and not os.path.exists(fail_once):
    open(fail_once, "w").close()
    sys.stderr.write(
        "avrdude: jtagmkII_getsync(): ISP activation failed, trying debugWIRE\\n"
        "avrdude: Target prepared for ISP, signed off.\\n"
        "avrdude: Please restart avrdude without power-cycling the target.\\n")
    sys.exit(1)

for a in args:
    parts = a.split(":")
    if len(parts) == 4 and parts[0] in ("lfuse", "hfuse", "efuse") and parts[1] == "r":
        value = int(os.environ.get("FAKE_" + parts[0].upper(), "0xFF"), 0)
        with open(parts[2], "wb") as fh:
            fh.write(bytes([value]))

sys.exit(int(os.environ.get("FAKE_AVRDUDE_RC", "0")))
'''


class FusesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = os.path.join(self.tmp.name, "blinky")
        with quiet():
            scaffold.create(self.proj, name="blinky", arch="avr")

        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        self.avrdude = os.path.join(self.bin, "avrdude")
        with open(self.avrdude, "w") as fh:
            fh.write(STUB)
        os.chmod(self.avrdude, os.stat(self.avrdude).st_mode | stat.S_IEXEC)

        self.log = os.path.join(self.tmp.name, "argv.log")
        self.env = {**os.environ, "PYTHONPATH": SRC,
                    "PATH": self.bin + os.pathsep + os.environ["PATH"],
                    "FAKE_AVRDUDE_LOG": self.log,
                    "FAKE_LFUSE": "0x62", "FAKE_HFUSE": "0xD9", "FAKE_EFUSE": "0xFF"}

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [line.strip() for line in fh if line.strip()]

    def writes(self):
        return [c for c in self.calls() if ":w:" in c]

    def mcu(self, *argv, project=None, env=None):
        return subprocess.run([sys.executable, "-m", "mcu",
                               "-C", project or self.proj, *argv],
                              capture_output=True, text=True, timeout=120,
                              env=env or self.env)

    # ---- read -----------------------------------------------------------

    def test_read_reports_the_three_fuses_and_dwen(self):
        r = self.mcu("fuses")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lfuse=0x62 hfuse=0xD9 efuse=0xFF", r.stdout)
        self.assertIn("DWEN unprogrammed (debugWIRE off)", r.stdout)
        self.assertIn("SPIEN programmed (ISP usable)", r.stdout)

    def test_read_spotlights_an_enabled_dwen(self):
        env = {**self.env, "FAKE_HFUSE": "0x99"}
        r = self.mcu("fuses", env=env)
        self.assertIn("DWEN PROGRAMMED (debugWIRE on)", r.stdout)

    # ---- DWEN -----------------------------------------------------------

    def test_dwen_on_clears_bit_6(self):
        r = self.mcu("fuses", "--dwen", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hfuse 0xD9 -> 0x99", r.stdout)
        self.assertTrue(any("hfuse:w:0x99:m" in c for c in self.writes()), self.writes())
        self.assertIn("power-cycled", r.stderr)          # the ISP takeover warning

    def test_dwen_off_sets_bit_6(self):
        env = {**self.env, "FAKE_HFUSE": "0x99"}
        r = self.mcu("fuses", "--dwen", "off", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hfuse 0x99 -> 0xD9", r.stdout)
        self.assertTrue(any("hfuse:w:0xD9:m" in c for c in self.writes()), self.writes())

    def test_dwen_on_is_idempotent(self):
        env = {**self.env, "FAKE_HFUSE": "0x99"}
        r = self.mcu("fuses", "--dwen", "on", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing written", r.stdout)
        self.assertEqual(self.writes(), [])

    def test_dwen_off_refuses_when_spien_is_gone(self):
        """No SPIEN means ISP cannot undo DWEN — say so instead of writing."""
        env = {**self.env, "FAKE_HFUSE": "0xF9"}
        r = self.mcu("fuses", "--dwen", "off", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("SPIEN is unprogrammed", r.stderr)
        self.assertIn("HVPP", r.stderr)
        self.assertEqual(self.writes(), [])

    def test_dwen_with_explicit_hfuse_is_rejected(self):
        r = self.mcu("fuses", "--dwen", "on", "--hfuse", "0xD9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--dwen derives hfuse", r.stderr)
        self.assertEqual(self.calls(), [])

    # ---- plain writes ---------------------------------------------------

    def test_writes_the_requested_fuse_only(self):
        r = self.mcu("fuses", "--lfuse", "0xFF")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any("lfuse:w:0xFF:m" in c for c in self.writes()), self.writes())
        self.assertFalse(any("hfuse:w" in c for c in self.writes()), self.writes())

    def test_decimal_and_bad_values(self):
        r = self.mcu("fuses", "--efuse", "255")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any("efuse:w:0xFF:m" in c for c in self.writes()), self.writes())
        r = self.mcu("fuses", "--lfuse", "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot parse lfuse", r.stderr)

    def test_avrdude_failure_is_reported(self):
        env = {**self.env, "FAKE_AVRDUDE_RC": "1"}
        r = self.mcu("fuses", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not read lfuse", r.stderr)

    # ---- prep and guards ------------------------------------------------

    def test_dry_run_needs_no_avrdude(self):
        env = {**self.env, "PATH": "/nonexistent"}
        r = self.mcu("-n", "fuses", "--lfuse", "0xFF", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-U lfuse:w:0xFF:m", r.stdout)
        self.assertEqual(self.calls(), [])

    def test_dry_run_dwen_shows_the_read_only(self):
        r = self.mcu("-n", "fuses", "--dwen", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hfuse:r:", r.stdout)
        self.assertIn("follows from that read", r.stdout)

    def test_debugwire_locked_target_is_retried(self):
        """avrdude prepares a DWEN target for ISP and asks to be run again."""
        flag = os.path.join(self.tmp.name, "failed-once")
        env = {**self.env, "FAKE_FAIL_ONCE": flag}
        r = self.mcu("fuses", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("retrying", r.stderr)
        self.assertIn("lfuse=0x62", r.stdout)
        # three fuse reads, plus one retry of the read that prepared the target
        self.assertEqual(len(self.calls()), 4, self.calls())

    def test_arm_project_has_no_fuses(self):
        arm = os.path.join(self.tmp.name, "samd")
        with quiet():
            scaffold.create(arm, name="samd", arch="arm")
        r = self.mcu("fuses", project=arm)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no fuse bytes", r.stderr)


if __name__ == "__main__":
    unittest.main()
