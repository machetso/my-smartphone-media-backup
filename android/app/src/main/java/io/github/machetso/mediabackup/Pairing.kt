package io.github.machetso.mediabackup

import android.content.Context
import android.net.Uri
import android.os.Build
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Pairing with a computer (commit-then-reveal, app 0.6.0):
 * 1. The computer's setup page opens  phonebackup://pair?pc=<ip:port>&t=<token>&id=<pc id>&name=<pc name>
 *    where token = SHA-256(key); the key itself stays on the computer for now.
 * 2. The phone sends its certificate fingerprint and a fresh random nonce to the computer
 *    (plain HTTP in the local network).
 * 3. The computer reveals the key over TLS pinned to that fingerprint (/reveal); the phone checks
 *    SHA-256(key) == token. Both now show code(key, fingerprint, nonce); the user confirms it on
 *    BOTH. A listener in the Wi-Fi never sees the key; a man in the middle must choose his values
 *    before he knows the key / the nonce, so the two codes differ.
 * 4. The computer claims a long-term secret with the key (/claim). Only after the confirmation on
 *    the phone; the pairing is then over.
 * The computer must be in the local network (private / link-local address, not the phone itself).
 */
object Pairing {
    data class Pending(val token: String, val pcAddress: String, val pcId: String, val pcName: String,
                       val nonce: String, val created: Long) {
        @Volatile var confirmed = false          // the user tapped "Pair" on the phone
        @Volatile var key: String? = null        // revealed by the computer over pinned TLS
        @Volatile var code: String? = null       // shown once the key is known
    }

    private fun isHex(s: String, len: IntRange) = s.length in len && s.all { it in "0123456789abcdef" }

    private fun newNonce(): String {
        val b = ByteArray(16)
        java.security.SecureRandom().nextBytes(b)
        return b.joinToString("") { "%02x".format(it) }
    }

    @Volatile var pending: Pending? = null
        private set

    fun parse(uri: Uri): Pending? {
        if (uri.scheme != "phonebackup" || uri.host != "pair") return null
        val pc = uri.getQueryParameter("pc") ?: return null
        if (!isLocalComputer(pc)) return null
        val token = uri.getQueryParameter("t") ?: return null
        if (!isHex(token, 64..64)) return null          // SHA-256 of the key (older computers: no)
        val id = (uri.getQueryParameter("id") ?: pc).take(80)
        val name = (uri.getQueryParameter("name") ?: "Computer").take(60)
        return Pending(token, pc, id, name, newNonce(), System.currentTimeMillis())
    }

    /** "a.b.c.d:port" of a computer in the local network: 10/8, 172.16/12, 192.168/16,
     *  169.254/16 (not the phone itself, not the internet). */
    fun isLocalComputer(address: String): Boolean {
        val m = Regex("""(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3}):(\d{1,5})""").matchEntire(address)
            ?: return false
        val b = m.groupValues.drop(1).take(4).map { it.toInt() }
        val port = m.groupValues[5].toInt()
        if (b.any { it > 255 } || port !in 1..65535) return false
        return b[0] == 10 || (b[0] == 172 && b[1] in 16..31) || (b[0] == 192 && b[1] == 168) ||
            (b[0] == 169 && b[1] == 254)
    }

    /** Step 3 on the phone: the user compared the code and tapped "Pair". */
    fun confirm(): Boolean {
        val p = pending ?: return false
        if (p.code == null) return false
        p.confirmed = true
        return true
    }

    /** Step 2 - runs in a background thread. Returns an error text or null. */
    fun announce(ctx: Context, p: Pending, serverPort: Int): String? {
        pending = p
        val body = JSONObject()
            .put("token", p.token)
            .put("fingerprint", Identity.fingerprint())
            .put("nonce", p.nonce)
            .put("port", serverPort)
            .put("phone_id", Identity.phoneId(ctx))
            .put("manufacturer", Build.MANUFACTURER)
            .put("model", Build.MODEL)
            .put("android", Build.VERSION.RELEASE)
            .toString().toByteArray()
        return try {
            val c = URL("http://${p.pcAddress}/pair").openConnection() as HttpURLConnection
            c.requestMethod = "POST"
            c.connectTimeout = 8000
            c.readTimeout = 15000
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(body) }
            val code = c.responseCode
            c.disconnect()
            if (code == 200) null else tr("The computer answered %d.", code)
        } catch (e: Exception) {
            tr("Could not reach the computer (%s): %s", p.pcAddress, e.message ?: "")
        }
    }

    private fun same(a: String?, b: String?) =
        a != null && b != null && java.security.MessageDigest.isEqual(a.toByteArray(), b.toByteArray())

    /** Step 3: the computer reveals the key (arrives over TLS, so only from whoever got our
     *  fingerprint). Accepted once, only if it matches the token from the link. */
    @Synchronized
    fun reveal(token: String?, key: String?): Boolean {
        val p = pending ?: return false
        if (!same(token, p.token) || key == null || !isHex(key, 32..128)) return false
        if (p.key != null) return same(key, p.key)
        if (!same(Identity.sha256Hex(key.toByteArray()), p.token)) return false
        p.key = key
        p.code = Identity.pairingCodeV2(key, Identity.fingerprint(), p.nonce)
        return true
    }

    /** Step 4. Returns (computer name, secret) or null. Pending pairings expire after 10 minutes. */
    @Synchronized
    fun claim(ctx: Context, token: String?, key: String?): Pair<String, String>? {
        val p = pending ?: return null
        if (!same(token, p.token) || p.key == null || !same(key, p.key)) return null
        if (System.currentTimeMillis() - p.created > 10 * 60_000) { pending = null; return null }
        if (!p.confirmed) return null            // not yet confirmed on the phone
        pending = null
        return p.pcName to Identity.addComputer(ctx, p.pcId, p.pcName)
    }

    fun cancel() { pending = null }

    /** For the server: is a pairing waiting for the user's tap on the phone? */
    fun waitingForConfirmation(token: String?, key: String?): Boolean {
        val p = pending ?: return false
        return !p.confirmed && same(token, p.token) && p.key != null && same(key, p.key)
    }
}
