# SPDX-License-Identifier: Apache-2.0
"""The software version and the schema version, in one place.

The software version names the build: `pyproject.toml` publishes this attribute as the
distribution's version, and a report prints it in its provenance. The schema version
names the shape of a trial document and changes only when that shape does.

Internal modules import both from here rather than from the package root. The root
re-exports the schema version as part of the public API, but the root also imports the
facade, so an internal module importing the root would close a cycle (root -> workspace
-> reports -> root) and see a half-initialized module. Keeping the constants in a leaf
module that imports nothing removes the load-order hazard entirely.
"""

softwareVersion = "0.1.0.dev0"
schemaVersion = "0.1.0"
