# SPDX-License-Identifier: Apache-2.0
"""`openfurrow scheduler` with the test kinds' runner: python schedulerWithTestKinds.py <store> <stopGraceSeconds>."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from openfurrow.tasks.scheduler import Scheduler  # noqa: E402

runner = [sys.executable, str(Path(__file__).parent / "runWithTestKinds.py")]
scheduler = Scheduler(sys.argv[1], pollSeconds=0.2, runCommand=runner, stopGraceSeconds=float(sys.argv[2]))
print("scheduling", flush=True)
scheduler.run()
print("stopped", flush=True)
