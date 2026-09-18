"""Config file handling and CLI wiring."""

import argparse
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcu import cli, config  # noqa: E402


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.toml")

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_without_a_file(self):
        cfg = config.load(os.path.join(self.tmp.name, "nope.toml"))
        self.assertEqual(cfg["baud"], 115200)
        self.assertEqual(cfg["led"], [])
        self.assertEqual(cfg["simavr_prefix"], "/usr/local")

    def test_file_overrides_defaults(self):
        if config.tomllib is None:
            self.skipTest("tomllib needs python >= 3.11")
        with open(self.path, "w") as fh:
            fh.write('[defaults]\n'
                     'mcu = "atmega2560"\n'
                     'freq = "8000000"\n'
                     'baud = 57600\n'
                     'led = ["D13", "PB0"]\n')
        cfg = config.load(self.path)
        self.assertEqual(cfg["mcu"], "atmega2560")
        self.assertEqual(cfg["freq"], "8000000")
        self.assertEqual(cfg["baud"], 57600)
        self.assertEqual(cfg["led"], ["D13", "PB0"])

    def test_broken_file_is_ignored(self):
        if config.tomllib is None:
            self.skipTest("tomllib needs python >= 3.11")
        with open(self.path, "w") as fh:
            fh.write("this is not toml at all = = =")
        cfg = config.load(self.path)
        self.assertEqual(cfg["baud"], 115200)

    def test_config_path_respects_xdg(self):
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        try:
            self.assertTrue(str(config.config_path()).startswith(self.tmp.name))
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME")
            else:
                os.environ["XDG_CONFIG_HOME"] = old


class TestCliWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "src"))
        with open(os.path.join(self.tmp.name, "CMakeLists.txt"), "w") as fh:
            fh.write('cmake_minimum_required(VERSION 3.20)\n'
                     'set(MCU   "atmega328p" CACHE STRING "")\n'
                     'set(F_CPU "16000000" CACHE STRING "")\n'
                     'project(blinky C)\n')
        os.makedirs(os.path.join(self.tmp.name, "build"))
        open(os.path.join(self.tmp.name, "build", "blinky.elf"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli.main(argv)
        except SystemExit as e:                      # commands call die()
            rc = e.code if isinstance(e.code, int) else 1
        return rc, out.getvalue(), err.getvalue()

    def test_version_and_help(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        rc, out, _ = self.run_cli([])
        self.assertEqual(rc, 1)
        self.assertIn("usage: mcu", out)

    def test_parser_has_all_commands(self):
        cmds = {"doctor", "list", "new", "build", "clean", "size",
                "flash", "monitor", "sim", "board", "debug", "trace"}
        got = set(cli.build_parser()._subparsers._group_actions[0].choices)
        self.assertEqual(cmds, got)

    def test_defaults_applied_after_config(self):
        args = cli.build_parser().parse_args(["board"])
        cli.apply_config(args, {"build_type": "Debug", "mcu": "atmega2560",
                                "led": ["D13"]})
        self.assertEqual(args.mcu, "atmega2560")
        self.assertEqual(args.led, ["D13"])

    def test_flags_beat_config(self):
        args = cli.build_parser().parse_args(["build", "--build-type", "Release"])
        cli.apply_config(args, {"build_type": "Debug"})
        self.assertEqual(args.build_type, "Release")

    def test_global_flags_before_and_after_the_subcommand(self):
        before = cli.build_parser().parse_args(["-C", "/tmp", "build"])
        after = cli.build_parser().parse_args(["build", "-C", "/tmp"])
        self.assertEqual(before.project, "/tmp")
        self.assertEqual(after.project, "/tmp")
        dry = cli.build_parser().parse_args(["-n", "build"])
        self.assertTrue(dry.dry_run)

    def test_dry_run_flash_shows_the_avrdude_argv(self):
        rc, out, _ = self.run_cli(["-C", self.tmp.name, "flash", "-n",
                                   "--port", "/dev/ttyUSB0"])
        self.assertEqual(rc, 0)
        self.assertIn("avrdude", out)
        self.assertIn("-c arduino", out)
        self.assertIn("-U flash:w:", out)

    def test_dry_run_flash_icsp(self):
        rc, out, _ = self.run_cli(["-C", self.tmp.name, "flash", "-n",
                                   "--method", "usbasp"])
        self.assertIn("-c usbasp", out)

    def test_no_project_gives_a_clear_error(self):
        # outside the project tree: `mcu` searches upwards, so an empty subdir
        # of a project is still that project
        with tempfile.TemporaryDirectory() as empty:
            rc, _, err = self.run_cli(["-C", empty, "build"])
        self.assertEqual(rc, 1)
        self.assertIn("no CMakeLists.txt", err)

    def test_firmware_missing_is_reported(self):
        os.remove(os.path.join(self.tmp.name, "build", "blinky.elf"))
        rc, _, err = self.run_cli(["-C", self.tmp.name, "sim"])
        self.assertEqual(rc, 1)
        self.assertIn("no firmware", err)

    def test_bad_press_spec_is_reported(self):
        rc, _, err = self.run_cli(["-C", self.tmp.name, "board",
                                   "--button", "D2", "--press", "oops", "-n"])
        self.assertEqual(rc, 1)
        self.assertIn("--press", err)

    def test_press_without_buttons_is_reported(self):
        rc, _, err = self.run_cli(["-C", self.tmp.name, "board",
                                   "--press", "1s:100ms", "-n"])
        self.assertEqual(rc, 1)
        self.assertIn("only 0 defined", err)

    def test_board_dry_run_lists_leds(self):
        rc, out, _ = self.run_cli(["-C", self.tmp.name, "board", "-n",
                                   "--led", "D13", "--button", "D2"])
        self.assertEqual(rc, 0)
        self.assertIn("harness: 1 led(s), 1 button(s)", out)


if __name__ == "__main__":
    unittest.main()
