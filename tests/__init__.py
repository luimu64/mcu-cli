"""Test suite for mcu-cli.

Run from the repository root:

    python -m unittest discover -s tests -v

Integration tests (scaffold -> build -> simulate) skip themselves when the
toolchain they need is not installed; `mcu doctor` lists what is missing.
"""

import contextlib
import io


@contextlib.contextmanager
def quiet():
    """Swallow command output so test logs stay readable."""
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        yield
