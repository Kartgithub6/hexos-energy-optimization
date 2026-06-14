"""Put src/ on the path so tests can `import engine...`."""
import sys, os
SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
