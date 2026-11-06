"""Tests NEVER touch the user's real settings or data (incident 2026-11-06: a test saved into the
real settings file and wiped the drive list, the phones and the pairings).

Before any test module is imported, every folder the program writes to is redirected into a
throw-away directory: settings (XDG_CONFIG_HOME / APPDATA), data (XDG_DATA_HOME / LOCALAPPDATA)
and HOME itself.
"""

import atexit
import os
import shutil
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="phonebackup-tests-")
for _var, _sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"),
                   ("APPDATA", "appdata"), ("LOCALAPPDATA", "localappdata"), ("HOME", "home"),
                   ("USERPROFILE", "home")):          # Windows: Path.home() uses USERPROFILE
    os.makedirs(os.path.join(_SANDBOX, _sub), exist_ok=True)
    os.environ[_var] = os.path.join(_SANDBOX, _sub)
os.environ["PHONEBACKUP_NO_ADB_OFFER"] = "1"
os.environ["PHONEBACKUP_TEST_SANDBOX"] = _SANDBOX
atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)
