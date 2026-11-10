package io.github.machetso.mediabackup

import org.junit.Assert.assertEquals
import org.junit.Test

/** Same values as phonebackup/wake.py (computer side, "Connect phone" QR code). */
class ConnectTokenTest {
    private val secret = "ab".repeat(32)

    @Test fun connectToken() =
        assertEquals("72f512fc3fe80b65", Connect.hmacHex(secret, "fmb-connect:0123456789abcdef:1800000000", 8))

    @Test fun hereProof() =
        assertEquals("8b712f5ad5b7178a521ff0a5dc00862e",
            Connect.hmacHex(secret, "fmb-here:0123456789abcdef:192.168.1.7:47823", 16))
}
