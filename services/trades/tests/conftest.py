import sys
from pathlib import Path

# Make the trades package importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
