# SPDX-License-Identifier: Apache-2.0
"""The schema version, in one place.

Internal modules import it from here rather than from the package root. The root
re-exports it as part of the public API, but the root also imports the facade, so an
internal module importing the root would close a cycle (root -> workspace -> reports
-> root) and see a half-initialized module. Keeping the constant in a leaf module
that imports nothing removes the load-order hazard entirely.
"""

schemaVersion = "0.1.0"
