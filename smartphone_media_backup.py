#!/usr/bin/env python3
"""Fast Smartphone Media Backup - start here.

    python smartphone_media_backup.py            graphical interface (needs PySide6)
    python smartphone_media_backup.py --cli      terminal version (no extra packages)
    python smartphone_media_backup.py backup|export|restore|settings   terminal, direct
"""

import sys

if sys.version_info < (3, 8):
    sys.exit("Fast Smartphone Media Backup needs Python 3.8 or newer.")


def run():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not args:
        try:
            from phonebackup import gui
        except ImportError as e:
            print(f"Graphical interface not available ({e}).\n"
                  "Install it with:  pip install PySide6   - starting the terminal version.\n")
        else:
            return gui.main()
    if args and args[0] == "--cli":
        args = args[1:]
    from phonebackup.app import main
    return main(args)


if __name__ == "__main__":
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        print("\nBye.")
