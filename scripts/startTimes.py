# SPDX-License-Identifier: Apache-2.0
"""Print how long the interpreter takes to start, bare and with the command line imported: every command-line test
and every command a person types pays these, so the validation workflow records them on each platform."""

from __future__ import annotations

import subprocess
import sys
import timeit


def bestOfThree(code: str) -> float:
  return min(timeit.repeat(lambda: subprocess.run([sys.executable, "-c", code], check=True), number=1, repeat=3))


def main() -> None:
  for label, code in (("bare start", "pass"), ("import openfurrow.cli.main", "import openfurrow.cli.main")):
    print(f"{label}: {bestOfThree(code):.2f} s")


if __name__ == "__main__":
  main()
