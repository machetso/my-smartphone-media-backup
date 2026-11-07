#!/usr/bin/env python3
"""Sign a release for the one-click update (run on YOUR computer, never on GitHub).

    python3 tools/sign_release.py keygen          # once: create the release key
    python3 tools/sign_release.py sign v0.9.7     # after CI built the (draft) release

The program installs an update only if `update-manifest.json` (version + SHA-256 and size of
every file) carries a valid signature of the release key. The private key lives only here:
    ~/.config/my-smartphone-media-backup-release/ed25519-signing.key
KEEP A COPY OF IT SOMEWHERE SAFE (e.g. a USB stick in a drawer). Without it no update can be
published that the installed programs accept (users would have to update once by hand).
If GitHub (or the account) is ever taken over, nobody can push a signed update without it.

`sign` downloads the release files with `gh`, writes the manifest, signs it and uploads
update-manifest.json + update-manifest.json.sig to the release.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phonebackup import ed25519  # noqa: E402
from phonebackup.selfupdate import MANIFEST, PUBLIC_KEY, SIGNATURE  # noqa: E402
from phonebackup.updatecheck import REPO, parse_version  # noqa: E402

KEY = Path.home() / ".config" / "my-smartphone-media-backup-release" / "ed25519-signing.key"


def keygen():
    if KEY.exists():
        sys.exit(f"{KEY} already exists - not overwritten.")
    KEY.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(KEY.parent, 0o700)
    secret = os.urandom(32)
    fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secret.hex() + "\n")
    print(f"Private key: {KEY}  (back it up!)")
    print(f'Public key for phonebackup/selfupdate.py:\nPUBLIC_KEY = "{ed25519.public_key(secret).hex()}"')


def manifest_for(version, folder):
    files = {}
    for p in sorted(Path(folder).iterdir()):
        if p.is_file() and p.name not in (MANIFEST, SIGNATURE):
            data = p.read_bytes()
            files[p.name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return json.dumps({"app": REPO, "version": version, "files": files}, indent=1, sort_keys=True).encode()


def sign(tag):
    if not parse_version(tag):
        sys.exit(f"not a version tag: {tag}")
    secret = bytes.fromhex(KEY.read_text().strip())
    if ed25519.public_key(secret).hex() != PUBLIC_KEY:
        sys.exit("This key does not belong to the PUBLIC_KEY in phonebackup/selfupdate.py.")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["gh", "release", "download", tag, "--repo", REPO, "--dir", tmp], check=True)
        for name in (MANIFEST, SIGNATURE):          # re-signing: the old manifest is replaced
            (Path(tmp) / name).unlink(missing_ok=True)
        data = manifest_for(tag.lstrip("v"), tmp)
        (Path(tmp) / MANIFEST).write_bytes(data)
        (Path(tmp) / SIGNATURE).write_text(ed25519.sign(secret, data).hex() + "\n")
        print(data.decode())
        subprocess.run(["gh", "release", "upload", tag, "--repo", REPO, "--clobber",
                        str(Path(tmp) / MANIFEST), str(Path(tmp) / SIGNATURE)], check=True)
    print(f"Signed and uploaded {MANIFEST} + {SIGNATURE} to {tag}.")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "keygen":
        keygen()
    elif len(sys.argv) == 3 and sys.argv[1] == "sign":
        sign(sys.argv[2])
    else:
        print(__doc__)
