"""Entry point for running the package as a module."""

import sys
import asyncio
from src.main import main

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
