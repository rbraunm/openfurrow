# SPDX-License-Identifier: Apache-2.0
"""Loading the OpenFurrow project configuration from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from openfurrow.config.profile import OpenFurrowConfig

# Convention: a project keeps all configuration in this single file. The folder
# grows into more files only if a real need appears.
defaultConfigRelativePath = Path("config") / "openfurrow.yaml"


def defaultConfig() -> OpenFurrowConfig:
  """The configuration used when a project has no config file: all defaults."""
  return OpenFurrowConfig()


def loadConfig(path: str | Path) -> OpenFurrowConfig:
  """Load and validate a project config file.

  An empty file is treated as all-defaults. A file whose root is not a mapping,
  or that carries an unknown section or setting, is rejected loud.
  """
  text = Path(path).read_text(encoding="utf-8")
  raw = yaml.safe_load(text)
  if raw is None:
    raw = {}
  if not isinstance(raw, dict):
    raise ValueError(f"config root must be a mapping, got {type(raw).__name__}")
  return OpenFurrowConfig.model_validate(raw)
