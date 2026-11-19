# SPDX-License-Identifier: Apache-2.0
"""Print how long the interpreter takes to start, bare and with the command line imported, and how long many small
files take to write: every command-line test and every store a test makes pays these, so the validation workflow
records them on each platform and a slow run can be told from a slow runner."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import timeit
from pathlib import Path


def bestOfThree(code: str) -> float:
  return min(timeit.repeat(lambda: subprocess.run([sys.executable, "-c", code], check=True), number=1, repeat=3))


def smallFiles(count: int) -> float:
  with tempfile.TemporaryDirectory() as folder:
    started = time.perf_counter()
    for number in range(count):
      Path(folder, f"{number}.txt").write_bytes(b"x" * 4096)
    return time.perf_counter() - started


def main() -> None:
  for label, code in (("bare start", "pass"), ("import openfurrow.cli.main", "import openfurrow.cli.main")):
    print(f"{label}: {bestOfThree(code):.2f} s")
  print(f"500 small files written: {smallFiles(500):.2f} s")


if __name__ == "__main__":
  main()
