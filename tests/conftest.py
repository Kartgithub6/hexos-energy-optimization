"""
conftest.py
===========
pytest loads this automatically before collecting tests. It puts the project's
src/ directory on the import path so test modules can `import build_model`,
`import data_io`, etc. without any per-file path juggling.
"""

import sys
import os

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
