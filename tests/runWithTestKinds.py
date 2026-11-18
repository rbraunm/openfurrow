# SPDX-License-Identifier: Apache-2.0
"""A run's process as `python -m openfurrow.tasks.run` starts it, with the test kinds registered too."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import taskKindsForTests  # noqa: E402,F401
from openfurrow.tasks.run import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
