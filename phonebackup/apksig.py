"""Who signed an Android app (APK)? - for "is the phone app on this phone really ours?".

The phone app can be downloaded over plain HTTP from the computer's setup page (phone browsers
do not trust a self-signed HTTPS certificate). Somebody in between could hand out a fake app.
Android only installs an APK whose signature is valid, so the SIGNING CERTIFICATE of the
installed app tells who made it. When the phone is on the cable, the computer reads the
installed APK and compares its signer with the one of the APK bundled in this program.

Reads the APK Signature Scheme v2 / v3 block (Android 7+; the phone app needs Android 8+).
Only the FIRST certificate of each signer is the signing certificate (more certificates in a
signer are an unverified chain), so only those are returned.
"""

import hashlib
import struct
from pathlib import Path

_MAGIC = b"APK Sig Block 42"
_V2, _V3, _V31 = 0x7109871A, 0xF05368C0, 0x1B93AD61
_EOCD_SIG = b"PK\x05\x06"


class ApkSigError(ValueError):
    pass


def _lp(buf, pos):
    """uint32-length-prefixed slice at pos → (slice, next pos)."""
    if pos + 4 > len(buf):
        raise ApkSigError("truncated")
    n = struct.unpack_from("<I", buf, pos)[0]
    pos += 4
    if pos + n > len(buf):
        raise ApkSigError("truncated")
    return buf[pos:pos + n], pos + n


def _seq(buf):
    pos, out = 0, []
    while pos < len(buf):
        item, pos = _lp(buf, pos)
        out.append(item)
    return out


def _signing_block(data):
    tail = data[-(65535 + 22):]
    i = tail.rfind(_EOCD_SIG)
    if i < 0 or i + 22 > len(tail):
        raise ApkSigError("not a zip file")
    cd_offset = struct.unpack_from("<I", tail, i + 16)[0]
    if cd_offset < 32 or cd_offset > len(data) or data[cd_offset - 16:cd_offset] != _MAGIC:
        raise ApkSigError("no APK signing block (v2/v3)")
    size = struct.unpack_from("<Q", data, cd_offset - 24)[0]
    start = cd_offset - size - 8
    if start < 0 or struct.unpack_from("<Q", data, start)[0] != size:
        raise ApkSigError("damaged APK signing block")
    return data[start + 8:cd_offset - 24]


def signer_certs(apk):
    """SHA-256 (hex) of the signing certificate of every signer in the v3 (else v2) block."""
    data = Path(apk).read_bytes() if not isinstance(apk, (bytes, bytearray)) else bytes(apk)
    block = _signing_block(data)
    pairs, pos = {}, 0
    while pos + 12 <= len(block):
        n = struct.unpack_from("<Q", block, pos)[0]
        if n < 4 or pos + 8 + n > len(block):
            raise ApkSigError("damaged APK signing block")
        pid = struct.unpack_from("<I", block, pos + 8)[0]
        pairs[pid] = block[pos + 12:pos + 8 + n]
        pos += 8 + n
    value = pairs.get(_V3) or pairs.get(_V31) or pairs.get(_V2)
    if value is None:
        raise ApkSigError("no v2/v3 signature")
    certs = set()
    signers, _ = _lp(value, 0)
    for signer in _seq(signers):
        signed_data, _ = _lp(signer, 0)
        _digests, p = _lp(signed_data, 0)
        cert_seq, _ = _lp(signed_data, p)
        cs = _seq(cert_seq)
        if cs:
            certs.add(hashlib.sha256(cs[0]).hexdigest())
    if not certs:
        raise ApkSigError("no signing certificate")
    return certs


def same_signer(apk_a, apk_b):
    """True when both APKs were signed with the same certificate."""
    return bool(signer_certs(apk_a) & signer_certs(apk_b))
