"""Guard: the tests really run in the sandbox (see tests/__init__.py)."""

import tests  # noqa: F401  - first module found: sets up the sandbox before any other test loads
import os
import unittest
from pathlib import Path

from phonebackup import adbdownload, config


class SandboxTest(unittest.TestCase):
    def test_settings_and_data_are_not_the_users(self):
        box = os.environ["PHONEBACKUP_TEST_SANDBOX"]
        self.assertTrue(str(config.config_path()).startswith(box), config.config_path())
        self.assertTrue(str(adbdownload.data_dir()).startswith(box), adbdownload.data_dir())
        self.assertTrue(str(Path.home()).startswith(box), Path.home())


if __name__ == "__main__":
    unittest.main()
