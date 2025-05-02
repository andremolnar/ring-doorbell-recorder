#!/usr/bin/env python
"""Run script for the Ring Doorbell Capture Application."""

import sys
import os
import asyncio
from pathlib import Path

# Add the project root to sys.path
project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Fix import issues by adding proper Python module path
sys.path.insert(0, project_root)

if __name__ == "__main__":
    from src.main import main
    sys.exit(asyncio.run(main()))
