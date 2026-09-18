"""Project discovery and the facts a project carries (MCU, clock, arch, outputs)."""

from __future__ import annotations

import os
import re

from .util import die


class Project:
    """A CMake-based firmware project.

    Nothing is hard-coded per board: the MCU/clock/target name are read from
    CMakeCache.txt once configured, falling back to the CMakeLists defaults, and
    the architecture is inferred from which toolchain file the project uses.
    """

    def __init__(self, path: str):
        self.dir = os.path.abspath(path)
        self.cmake = os.path.join(self.dir, "CMakeLists.txt")
        self.build = os.path.join(self.dir, "build")

    # ---- discovery -------------------------------------------------------
    @staticmethod
    def find(start: str | None = None) -> "Project":
        d = os.path.abspath(start or os.getcwd())
        while True:
            if os.path.isfile(os.path.join(d, "CMakeLists.txt")):
                return Project(d)
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        die(f"no CMakeLists.txt found from {start or os.getcwd()} upwards")

    def cmake_text(self) -> str:
        try:
            with open(self.cmake) as fh:
                return fh.read()
        except OSError:
            return ""

    def cached(self, key: str):
        try:
            with open(os.path.join(self.build, "CMakeCache.txt")) as fh:
                for line in fh:
                    if line.startswith(key + ":"):
                        return line.split("=", 1)[1].strip()
        except OSError:
            pass
        return None

    def _from_cmakelists(self, var: str):
        m = re.search(rf'set\(\s*{var}\s+"?([A-Za-z0-9_]+)"?', self.cmake_text())
        return m.group(1) if m else None

    # ---- facts -----------------------------------------------------------
    @property
    def arch(self) -> str:
        """avr or arm — decided by what the project references, not by the host."""
        t = self.cmake_text()
        low = t.lower()
        if "avr-gcc.cmake" in t:
            return "avr"
        if "arm-gcc.cmake" in t:
            return "arm"
        if ("arm-none-eabi" in low or "-mcpu=" in low
                or "cortex-m" in low or "cmsis" in low):
            return "arm"
        if re.search(r"avr-|mmcu=|at(mega|tiny|xmega)\d|at90", low):
            return "avr"
        if "-mmcu" in low or re.search(r"^\s*set\(\s*MCU\b", t, re.M):
            return "avr"
        # last resort: whichever cross compiler this host actually has
        from .util import have
        if have("avr-gcc"):
            return "avr"
        return "arm" if have("arm-none-eabi-gcc") else "avr"

    @property
    def name(self) -> str:
        m = re.search(r"project\(\s*([A-Za-z0-9_\-]+)", self.cmake_text())
        return m.group(1) if m else os.path.basename(self.dir)

    @property
    def mcu(self) -> str:
        v = (self.cached("MCU") or self.cached("MCU_PART")
             or self._from_cmakelists("MCU"))
        if v:
            return v
        if self.arch == "avr":
            return "atmega328p"
        cpu = self._from_cmakelists("CPU") or ""
        m = re.search(r"-mcpu=([A-Za-z0-9\-]+)", cpu + self.cmake_text())
        return m.group(1) if m else "cortex-m0plus"

    @property
    def freq(self) -> str:
        v = (self.cached("F_CPU") or self._from_cmakelists("F_CPU")
             or self._from_cmakelists("CPU_HZ") or "16000000")
        return re.sub(r"[ULul]+$", "", str(v))

    def _output(self, ext: str) -> str:
        direct = os.path.join(self.build, self.name + ext)
        if os.path.isfile(direct):
            return direct
        if os.path.isdir(self.build):
            for f in sorted(os.listdir(self.build)):
                if f.endswith(ext):
                    return os.path.join(self.build, f)
        return direct

    @property
    def elf(self) -> str:
        return self._output(".elf")

    @property
    def hex(self) -> str:
        return self._output(".hex")

    @property
    def bin(self) -> str:
        return self._output(".bin")

    # ---- build wiring ----------------------------------------------------
    def configured(self) -> bool:
        return os.path.isfile(os.path.join(self.build, "build.ninja"))

    def toolchain_file(self) -> str:
        return "avr-gcc.cmake" if self.arch == "avr" else "arm-gcc.cmake"

    def configure_cmd(self, build_type: str = "Release"):
        return ["cmake", "-B", "build", "-G", "Ninja",
                f"-DCMAKE_BUILD_TYPE={build_type}",
                f"-DCMAKE_TOOLCHAIN_FILE={self.toolchain_file()}"]

    def size_cmd(self):
        if self.arch == "avr":
            return ["avr-size", "--format=avr", f"--mcu={self.mcu}", self.elf]
        return ["arm-none-eabi-size", "-A", "-d", self.elf]
