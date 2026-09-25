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

state_path = os.environ.get("FAKE_FUSE_STATE")


def _state():
    """AVR8X fuse block: 10 bytes, seeded from FAKE_FUSES or all-ones."""
    if state_path and os.path.exists(state_path):
        with open(state_path, "rb") as fh:
            return bytearray(fh.read())        # may be empty: tests that
    seed = os.environ.get("FAKE_FUSES", "").replace(" ", "")
    data = bytearray.fromhex(seed) if seed else bytearray(b"\\xff" * 10)
    while len(data) < 10:
        data.append(0xFF)
    return data


for a in args:
    parts = a.split(":")
    if len(parts) == 4 and parts[0] in ("lfuse", "hfuse", "efuse") and parts[1] == "r":
        value = int(os.environ.get("FAKE_" + parts[0].upper(), "0xFF"), 0)
        with open(parts[2], "wb") as fh:
            fh.write(bytes([value]))
    elif len(parts) == 4 and parts[0] == "fuses" and parts[1] == "r":
        with open(parts[2], "wb") as fh:
            fh.write(bytes(_state()))
    elif len(parts) == 4 and len(parts[0]) == 5 and parts[0].startswith("fuse") \\
            and parts[1] == "w" and state_path:
        # AVR8X: keep the byte so a read-back after the write sees it
        data = _state()
        data[int(parts[0][4:])] = int(parts[2], 0)
        with open(state_path, "wb") as fh:
            fh.write(bytes(data))

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
        # drop any FAKE_* the caller's environment happens to export, so the stub
        # only ever sees what a test sets here
        base_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        self.env = {**base_env, "PYTHONPATH": SRC,
                    "PATH": self.bin + os.pathsep + base_env["PATH"],
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

    def test_part_comes_from_the_project_not_the_cli_default(self):
        """`mcu -C <dir> fuses` in a non-328P project must not fall back to the
        CLI's `args.mcu` default (m328p) — that would program the wrong chip."""
        big = os.path.join(self.tmp.name, "big")
        with quiet():
            scaffold.create(big, name="big", arch="avr", mcu="atmega4809",
                            freq="20000000")
        r = self.mcu("-n", "fuses", "--programmer", "atmelice_updi", project=big)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-p atmega4809", r.stdout)
        self.assertNotIn("-p m328p", r.stdout)

    def test_arm_project_has_no_fuses(self):
        arm = os.path.join(self.tmp.name, "samd")
        with quiet():
            scaffold.create(arm, name="samd", arch="arm")
        r = self.mcu("fuses", project=arm)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no fuse bytes", r.stderr)


class FusesAvr8xTest(unittest.TestCase):
    """AVR8X (ATmega4809): one 10-byte fuse block, UPDI only, no lfuse/hfuse/efuse.

    Same stub as above: it plays the chip, keeps the written byte in a state file
    and hands the whole block back on the next `fuses:r:` read.
    """

    FACTORY = "00 00 7E FF FF F6 FF 00 00 00"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = os.path.join(self.tmp.name, "nano_every")
        with quiet():
            scaffold.create(self.proj, name="nano_every", arch="avr",
                            mcu="atmega4809", freq="20000000")

        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        self.avrdude = os.path.join(self.bin, "avrdude")
        with open(self.avrdude, "w") as fh:
            fh.write(STUB)
        os.chmod(self.avrdude, os.stat(self.avrdude).st_mode | stat.S_IEXEC)

        self.log = os.path.join(self.tmp.name, "argv.log")
        self.state = os.path.join(self.tmp.name, "fuse-state.bin")
        base_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        self.env = {**base_env, "PYTHONPATH": SRC,
                    "PATH": self.bin + os.pathsep + base_env["PATH"],
                    "FAKE_AVRDUDE_LOG": self.log,
                    "FAKE_FUSES": self.FACTORY,
                    "FAKE_FUSE_STATE": self.state}
        self.updi = ["--programmer", "atmelice_updi"]

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [line.strip() for line in fh if line.strip()]

    def writes(self):
        return [c for c in self.calls() if ":w:" in c]

    def mcu(self, *argv, env=None):
        return subprocess.run([sys.executable, "-m", "mcu", "-C", self.proj, *argv],
                              capture_output=True, text=True, timeout=120,
                              env=env or self.env)

    # ---- read -----------------------------------------------------------

    def test_read_shows_the_block_and_the_bit_fields(self):
        r = self.mcu("fuses", *self.updi)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fuses@0x1280 = 00 00 7E FF FF F6 FF 00 00 00", r.stdout)
        self.assertIn("5 SYSCFG0=0xF6", r.stdout)
        self.assertIn("2 OSCCFG=0x7E", r.stdout)
        # 0xF6 is the header's FUSE_SYSCFG0_DEFAULT: RSTPINCFG=0 (GPIO mode)
        self.assertIn("RSTPINCFG=(0xF6 & 0x08) >> 3 = 0 (PA0 is a plain I/O pin)",
                      r.stdout)
        self.assertIn("OSCLOCK=(0x7E & 0x80) >> 7 = 0", r.stdout)
        self.assertIn("UPDIPINCFG", r.stdout)        # tinyAVR caveat
        self.assertNotIn("lfuse", r.stdout)
        self.assertTrue(any("-U fuses:r:" in c for c in self.calls()), self.calls())
        self.assertTrue(any("-p atmega4809" in c for c in self.calls()), self.calls())
        self.assertTrue(any("-c atmelice_updi" in c for c in self.calls()), self.calls())

    # ---- write ----------------------------------------------------------

    def test_write_by_name_then_read_back(self):
        r = self.mcu("fuses", *self.updi, "--fuse", "SYSCFG0=0xF5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SYSCFG0 (fuse5) 0xF6 -> 0xF5", r.stdout)
        self.assertTrue(any("-U fuse5:w:0xF5:m" in c for c in self.writes()), self.writes())
        # the read-back inside the same run must show the new byte
        self.assertIn("fuses@0x1280 = 00 00 7E FF FF F5 FF 00 00 00", r.stdout)
        self.assertIn("wrote SYSCFG0=0xF5", r.stdout)

    def test_write_by_bit_name_and_fuse_number(self):
        r = self.mcu("fuses", *self.updi, "--fuse", "OSCCFG=0x7F",
                     "--fuse", "fuse8=0x02")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any("-U fuse2:w:0x7F:m" in c for c in self.writes()), self.writes())
        self.assertTrue(any("-U fuse8:w:0x02:m" in c for c in self.writes()), self.writes())
        self.assertIn("wrote OSCCFG=0x7F, BOOTEND=0x02", r.stdout)

    def test_codesize_alias_maps_to_fuse7(self):
        r = self.mcu("-n", "fuses", *self.updi, "--fuse", "CODESIZE=0x01")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-U fuse7:w:0x01:m", r.stdout)

    def test_rstpincfg_change_warns_about_updi_entry(self):
        """0xF6 -> 0xFE flips RSTPINCFG 0->1 (GPIO -> Reset mode)."""
        r = self.mcu("fuses", *self.updi, "--fuse", "SYSCFG0=0xFE")
        self.assertIn("SYSCFG0.RSTPINCFG 0 -> 1", r.stderr)
        self.assertIn("fuse override", r.stderr)
        # the other direction says something different
        env = {**self.env, "FAKE_FUSES": "00 00 7E FF FF FE FF 00 00 00"}
        r = self.mcu("fuses", *self.updi, "--fuse", "SYSCFG0=0xF6", env=env)
        self.assertIn("SYSCFG0.RSTPINCFG 1 -> 0", r.stderr)
        self.assertIn("GPIO mode", r.stderr)

    def test_no_warning_when_rstpincfg_is_untouched(self):
        r = self.mcu("fuses", *self.updi, "--fuse", "SYSCFG0=0xF5")
        self.assertNotIn("RSTPINCFG 0", r.stderr)

    def test_bad_value_and_unknown_name(self):
        r = self.mcu("fuses", *self.updi, "--fuse", "SYSCFG0=0x1FF")
        self.assertEqual(r.returncode, 1)
        r = self.mcu("fuses", *self.updi, "--fuse", "FUSE42=0x00")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown AVR8X fuse", r.stderr)
        r = self.mcu("fuses", *self.updi, "--fuse", "SYSCFG0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NAME=HEX", r.stderr)

    def test_avrdude_failure_names_the_programmer(self):
        env = {**self.env, "FAKE_AVRDUDE_RC": "1"}
        r = self.mcu("fuses", *self.updi, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not read the fuse block", r.stderr)

    def test_empty_read_is_caught(self):
        """avrdude exit 0 with no data must not look like success."""
        env = {**self.env, "FAKE_FUSES": ""}
        open(self.state, "wb").close()               # zero-length state file
        r = self.mcu("fuses", *self.updi, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("wrote no fuse data", r.stderr)

    # ---- refusals -------------------------------------------------------

    def test_udpi_programmer_is_required(self):
        r = self.mcu("fuses")                        # no --programmer
        self.assertEqual(r.returncode, 1)
        self.assertIn("UPDI", r.stderr)
        self.assertIn("atmelice_updi", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_classic_fuse_names_are_refused_with_a_mapping(self):
        for name, expect in (("--lfuse", "OSCCFG"), ("--hfuse", "SYSCFG0"),
                             ("--efuse", "BODCFG")):
            r = self.mcu("fuses", *self.updi, name, "0xFF")
            self.assertEqual(r.returncode, 1, name)
            self.assertIn("AVR8X has no", r.stderr)
            self.assertIn(expect, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_dwen_is_refused_and_maps_to_rstpincfg(self):
        r = self.mcu("fuses", *self.updi, "--dwen", "on")
        self.assertEqual(r.returncode, 1)
        self.assertIn("RSTPINCFG", r.stderr)
        self.assertIn("UPDI", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_fuse_flag_is_refused_on_a_classic_part(self):
        classic = os.path.join(self.tmp.name, "uno")
        with quiet():
            scaffold.create(classic, name="uno", arch="avr")
        r = subprocess.run([sys.executable, "-m", "mcu", "-C", classic, "fuses",
                            "--fuse", "SYSCFG0=0xF6"],
                           capture_output=True, text=True, timeout=120, env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("classic AVR8", r.stderr)

    # ---- no simulator ---------------------------------------------------

    def test_sim_is_refused_for_avr8x(self):
        for cmd in ("sim", "board", "trace"):
            r = self.mcu(cmd)
            self.assertEqual(r.returncode, 1, cmd)
            self.assertIn("simavr has no atmega4809 core", r.stderr)
        r = self.mcu("debug")
        self.assertEqual(r.returncode, 1)
        self.assertIn("bench-only", r.stderr)

    def test_flash_asks_for_a_udpi_programmer(self):
        r = self.mcu("flash")                        # auto -> bootloader
        self.assertEqual(r.returncode, 1)
        self.assertIn("no serial bootloader", r.stderr)
        r = self.mcu("flash", "--method", "icsp")
        self.assertEqual(r.returncode, 1)
        self.assertIn("atmelice_updi", r.stderr)


if __name__ == "__main__":
    unittest.main()
