"""Private worker entry point used by the acceptance scheduler probe."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.acceptance_support import run_worker

if __name__ == '__main__':
    run_worker(sys.argv[1])
