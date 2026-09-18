# Contributing

Bug reports and patches are welcome. `mcu` is deliberately small: one Python package,
no runtime dependencies, and every command is a thin layer over a standard tool.

## Getting set up

```sh
git clone git@github.com:luimu64/mcu-cli.git
cd mcu-cli
python -m venv .venv && . .venv/bin/activate
pip install -e .

mcu doctor                          # what this machine has
python -m unittest discover -s tests -v
```

Integration tests (scaffold → build → simulate) skip themselves when the relevant
toolchain is missing, so the suite is useful on a bare machine and thorough on one with
`avr-gcc`, `simavr` and `arm-none-eabi-gcc`.

## Guidelines

- **No new runtime dependencies.** Everything runs on the standard library, on Python
  3.9+. Optional features must degrade gracefully (`tomllib` config parsing is guarded).
- **Keep commands thin.** A command resolves its inputs, then calls a normal tool. Logic
  that belongs in `avrdude` or `cmake` does not belong here.
- **Generalise, don't special-case a board.** Board-specific facts belong in flags or in
  the project (`MCU`, `F_CPU`, toolchain file), not in a hard-coded table. If something
  only works for one part, say so in the message or the docs.
- **Do not probe a simulator's gdb port with a TCP connect.** simavr accepts a single
  connection; the probe consumes it and the real client hangs. Wait on the process.
- **Generated files stay disposable.** `mcu new` output and `sim/generated/` must be
  regenerable from flags at any time, and never be required for an existing project to
  work.
- Tests: add a unit test for parsing/derivation logic and an integration test for
  anything that shells out. Prefer asserting on behaviour (files produced, output text)
  over internal calls.

## Reporting

Include the output of `mcu doctor`, the exact command, and what happened. If it is a
simulation problem, `mcu board ... -n` (dry run) plus the first lines of the generated
`sim/generated/board.c` usually identify it immediately.
