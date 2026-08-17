# SPDX-License-Identifier: Apache-2.0
"""Tests for the shipped reference configuration file.

`examples/openfurrow.yaml` documents every project setting at its default value, as a
file users copy and trim. That only helps if it stays correct, and nothing else would
notice if it did not: a config example that has drifted from the schema is worse than
no example, because a user copies it and hits a loud rejection on a key that no longer
exists. These tests keep it honest.
"""

from pathlib import Path

from openfurrow.config import defaultConfig, defaultConfigRelativePath, loadConfig

_referencePath = Path(__file__).resolve().parent.parent / "examples" / "openfurrow.yaml"


def testReferenceConfigExists():
  assert _referencePath.exists(), "the reference config examples/openfurrow.yaml is missing"


def testReferenceConfigLoadsAndMatchesDefaults():
  """It must load, and it must genuinely equal the defaults it claims to show.

  The config model forbids unknown keys, so a setting that was renamed or removed makes
  this fail loudly. If a setting is added or a default changes, this fails until the
  reference is updated -- which is the point.
  """
  assert loadConfig(_referencePath) == defaultConfig()


def testReferenceConfigDocumentsEveryTopLevelSection():
  """Every section of the config model appears in the reference file.

  A section missing from the example is a setting users cannot discover without reading
  the source.
  """
  text = _referencePath.read_text(encoding="utf-8")
  for section in defaultConfig().model_dump(by_alias=True):
    assert f"\n{section}:" in text, f"the reference config does not document the '{section}' section"


def testReferenceConfigMatchesTheDocumentedConventionalPath():
  """The reference names the conventional location the loader documents."""
  assert defaultConfigRelativePath.as_posix() in _referencePath.read_text(encoding="utf-8")
