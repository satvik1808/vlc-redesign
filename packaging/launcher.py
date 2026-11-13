"""Entry point for the packaged (PyInstaller) build."""
import sys

from vlcredesign.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
