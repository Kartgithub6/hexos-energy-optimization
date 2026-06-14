"""Add src/ and config/ to sys.path for the scenario scripts."""
import sys, os
HERE = os.path.dirname(__file__)
for p in ("../src", "../config"):
    ap = os.path.join(HERE, p)
    if ap not in sys.path:
        sys.path.insert(0, ap)
