"""Make ``pytest`` work without installing the package.

Keeping the test suite runnable straight from a clone matters for contributors:
`pip install -e .` needs network, a build backend and a writable site-packages.
None of that should stand between a first-time contributor and a green run.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
