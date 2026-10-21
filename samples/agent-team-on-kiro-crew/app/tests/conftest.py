import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))          # `import backend.routes` (bootstrap) and tests' own helpers
sys.path.insert(0, str(ROOT / "tests"))
