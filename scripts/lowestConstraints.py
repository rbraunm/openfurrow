# SPDX-License-Identifier: Apache-2.0
"""Print a pip constraints file that pins every direct dependency to the lowest version pyproject.toml allows.

The validation workflow installs with it on the oldest supported Python, so the lower bounds
stated in pyproject.toml are bounds the suite has passed on, not guesses. A dependency
written without a lower bound is refused: every direct dependency states one.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

requirementPattern = re.compile(r"^\s*([A-Za-z0-9._-]+)(\[[^\]]+\])?\s*>=\s*([0-9][0-9A-Za-z.]*)\s*(;.*)?$")


def lowestPins(project: dict) -> list[str]:
  requirements = list(project["dependencies"])
  for extra in project.get("optional-dependencies", {}).values():
    requirements.extend(extra)
  pins: dict[str, str] = {}
  for requirement in requirements:
    match = requirementPattern.match(requirement)
    if match is None:
      raise SystemExit(f"'{requirement}' does not state a lower bound as name>=version")
    name, version, marker = match.group(1).lower(), match.group(3), match.group(4) or ""
    line = f"{name}=={version}{marker}"
    if pins.setdefault(name, line) != line:
      raise SystemExit(f"'{name}' is stated with two different lower bounds")
  return sorted(pins.values())


def main() -> None:
  pyproject = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "pyproject.toml"
  with pyproject.open("rb") as handle:
    project = tomllib.load(handle)["project"]
  print("\n".join(lowestPins(project)))


if __name__ == "__main__":
  main()
