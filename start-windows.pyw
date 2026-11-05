# Windows: double-click this file to start My Smartphone Media Backup without a console window.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phonebackup import gui  # noqa: E402

sys.exit(gui.main())
