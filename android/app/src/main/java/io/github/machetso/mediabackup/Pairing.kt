package io.github.machetso.mediabackup

import android.content.Context
import android.net.Uri
import android.os.Build
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Pairing with a computer:
 * 1. The computer's setup page opens  phonebackup://pair?pc=<ip:port>&t=<token>&id=<pc id>&name=<pc name>
 * 2. The phone sends its certificate fingerprint to the computer (plain HTTP in the local network).
 * 3. Phone and computer show the same 6-digit code; the user confirms it on the computer.
 * 4. The computer connects over TLS (pinned fingerprint) and claims a long-term secret with the
 *    one-time token (/claim on the server). The token is then invalid.
 */
object Pairing {
    data class Pending(val token: String, val pcAddress: String, val pcId: String, val pcName: String,
                       val code: String, val created: Long)

    @Volatile var pending: Pending? = null
        private set

    fun parse(uri: Uri): Pending? {
        if (uri.scheme != "phonebackup" || uri.host != "pair") return null
        val pc = uri.getQueryParameter("pc") ?: return null
        val token = uri.getQueryParameter("t") ?: return null
        if (token.length < 16) return null
        val id = uri.getQueryParameter("id") ?: pc
        val name = uri.getQueryParameter("name") ?: "Computer"
        return Pending(token, pc, id, name, Identity.pairingCode(token, Identity.fingerprint()), System.currentTimeMillis())
    }

    /** Step 2 - runs in a background thread. Returns an error text or null. */
    fun announce(ctx: Context, p: Pending, serverPort: Int): String? {
        pending = p
        val body = JSONObject()
            .put("token", p.token)
            .put("fingerprint", Identity.fingerprint())
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
            if (code == 200) null else "The computer answered $code."
        } catch (e: Exception) {
            "Could not reach the computer (${p.pcAddress}): ${e.message}"
        }
    }

    /** Step 4. Returns (computer name, secret) or null. Pending pairings expire after 10 minutes. */
    @Synchronized
    fun claim(ctx: Context, token: String?): Pair<String, String>? {
        val p = pending ?: return null
        if (token == null || !java.security.MessageDigest.isEqual(token.toByteArray(), p.token.toByteArray())) return null
        if (System.currentTimeMillis() - p.created > 10 * 60_000) { pending = null; return null }
        pending = null
        return p.pcName to Identity.addComputer(ctx, p.pcId, p.pcName)
    }

    fun cancel() { pending = null }
}
