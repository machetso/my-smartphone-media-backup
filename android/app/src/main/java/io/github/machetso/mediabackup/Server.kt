package io.github.machetso.mediabackup

import android.content.Context
import android.os.Build
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.concurrent.Executors
import javax.net.ssl.SSLServerSocket

/**
 * The backup server: TLS (phone certificate, pinned by the computer) + a secret per paired
 * computer. READ ONLY - it can list, hash and send photos/videos and nothing else.
 */
class Server(private val ctx: Context, private val onEvent: (String) -> Unit) {
    companion object {
        const val PREFERRED_PORT = 47823
        const val PROTOCOL = 1
        const val MAX_CONNECTIONS = 24
    }

    private val media = MediaIndex(ctx)
    // bounded: unauthenticated connections cannot create unlimited threads
    private val pool = java.util.concurrent.ThreadPoolExecutor(
        2, MAX_CONNECTIONS, 60L, java.util.concurrent.TimeUnit.SECONDS,
        java.util.concurrent.SynchronousQueue())
    private var socket: ServerSocket? = null
    @Volatile var lastActivity = System.currentTimeMillis()
        private set
    val port get() = socket?.localPort ?: 0

    fun start() {
        val ss = Identity.sslContext().serverSocketFactory.createServerSocket() as SSLServerSocket
        ss.reuseAddress = true
        try {
            ss.bind(InetSocketAddress(PREFERRED_PORT))
        } catch (e: java.io.IOException) {
            ss.bind(InetSocketAddress(0))
        }
        socket = ss
        Thread({
            while (!ss.isClosed) {
                val s = try { ss.accept() } catch (e: SocketException) { break } catch (e: Exception) { continue }
                if (!isLocalPeer(s.inetAddress)) {        // e.g. mobile data / public IPv6
                    try { s.close() } catch (_: Exception) {}
                    continue
                }
                try {
                    pool.execute { serve(s) }
                } catch (e: java.util.concurrent.RejectedExecutionException) {
                    try { s.close() } catch (_: Exception) {}
                }
            }
        }, "server-accept").apply { isDaemon = true; start() }
    }

    fun stop() {
        try { socket?.close() } catch (_: Exception) {}
        pool.shutdownNow()
    }

    /** Loopback (adb forward over the cable) or the local network – never the internet. */
    private fun isLocalPeer(a: java.net.InetAddress?): Boolean {
        if (a == null) return false
        if (a.isLoopbackAddress || a.isSiteLocalAddress || a.isLinkLocalAddress) return true
        val b = a.address
        return a is java.net.Inet6Address && (b[0].toInt() and 0xfe) == 0xfc   // fc00::/7 (ULA)
    }

    private fun serve(s: Socket) {
        s.use { sock ->
            sock.soTimeout = 120_000
            val inp = BufferedInputStream(sock.getInputStream(), 1 shl 16)
            val out = BufferedOutputStream(sock.getOutputStream(), 1 shl 18)
            try {
                while (true) {
                    val req = Request.read(inp) ?: return
                    val keep = handle(req, out, sock.inetAddress?.isLoopbackAddress == true)
                    if (!keep || !req.keepAlive) return
                }
            } catch (_: Exception) {
                // connection dropped / TLS error / bad request: just close it
            }
        }
    }

    private fun jsonBody(req: Request) = JSONObject(String(req.body, Charsets.UTF_8))

    /** Returns false to close the connection. */
    private fun handle(req: Request, out: BufferedOutputStream, viaCable: Boolean): Boolean {
        val keep = req.keepAlive
        // ---- pairing over the USB cable (adb forward ends on the phone's loopback address).
        // The user confirms it on the phone; other apps on the phone could also reach loopback.
        if (req.method == "POST" && (req.path == "/usbpair" || req.path == "/usbpair/claim")) {
            if (!viaCable) {
                Response.json(out, 403, """{"error":"only over the USB cable"}""", false)
                return false
            }
            val body = runCatching { jsonBody(req) }.getOrNull()
            val pcId = body?.optString("pc_id").orEmpty()
            if (pcId.length < 8) {
                Response.json(out, 400, """{"error":"pc_id missing"}""", false)
                return false
            }
            if (req.path == "/usbpair") {
                // the computer's random value → code from it + THIS phone's key, shown on both
                // screens: an app that put itself in between (own key) cannot produce it
                val nonce = body?.optString("nonce").orEmpty()
                if (nonce.length !in 16..128) {
                    Response.json(out, 400, """{"error":"nonce missing"}""", false)
                    return false
                }
                val code = Identity.pairingCode(nonce, Identity.fingerprint())
                if (!CablePairing.request(pcId, body?.optString("pc_name").orEmpty().ifEmpty { "Computer" }.take(60), code)) {
                    Response.json(out, 409, """{"error":"another pairing request is waiting on the phone"}""", false)
                    return false
                }
                onEvent("PAIR_REQUEST")
                Response.json(out, 202, """{"pending":true}""", keep)
                return keep
            }
            when (CablePairing.state(pcId)) {
                CablePairing.State.ACCEPTED -> {
                    val name = CablePairing.take(pcId) ?: "Computer"
                    val secret = Identity.addComputer(ctx, pcId, name)
                    Response.json(out, 200, JSONObject().put("secret", secret)
                        .put("phone_id", Identity.phoneId(ctx)).toString(), keep)
                    onEvent("Paired with $name")
                }
                CablePairing.State.REFUSED -> {
                    CablePairing.take(pcId)
                    Response.json(out, 403, """{"error":"refused on the phone"}""", keep)
                }
                CablePairing.State.PENDING -> Response.json(out, 202, """{"pending":true}""", keep)
                CablePairing.State.NONE -> Response.json(out, 404, """{"error":"no pairing request"}""", keep)
            }
            return keep
        }
        // ---- pairing: the one request that does not need a secret (needs the one-time token)
        if (req.method == "POST" && req.path == "/claim") {
            val token = runCatching { jsonBody(req).getString("token") }.getOrNull()
            if (Pairing.waitingForConfirmation(token)) {     // the computer asks again in a moment
                Response.json(out, 409, """{"error":"confirm on the phone","wait":true}""", false)
                return false
            }
            val pc = Pairing.claim(ctx, token)
            if (pc == null) {
                Response.json(out, 403, """{"error":"no pairing pending or wrong token"}""", false)
                return false
            }
            Response.json(out, 200, JSONObject().put("secret", pc.second).put("phone_id", Identity.phoneId(ctx)).toString(), keep)
            onEvent("Paired with ${pc.first}")
            return keep
        }
        val auth = req.headers["authorization"]?.removePrefix("Bearer ")?.trim()
        val pc = Identity.computerFor(ctx, auth)
        if (pc == null) {
            Response.json(out, 401, """{"error":"not paired"}""", false)
            return false
        }
        lastActivity = System.currentTimeMillis()    // only a PAIRED computer keeps backup mode on
        // ---- debugging guard (see UsbDebug): start / still here / end of a backup
        when ("${req.method} ${req.path}") {
            "POST /guard/start" -> {
                val channel = runCatching { jsonBody(req).optString("channel") }.getOrNull().orEmpty()
                UsbDebug.Guard.backupStarted(ctx, channel)
                Response.json(out, 200, JSONObject().put("can_switch", UsbDebug.canSwitch(ctx))
                    .put("via_cable", viaCable).toString(), keep)
                return keep
            }
            "GET /info" -> {          // also without photo access: the computer checks the phone first
                Response.json(out, 200, JSONObject()
                    .put("protocol", PROTOCOL)
                    .put("app_version", BuildConfigInfo.versionName(ctx))
                    .put("phone_id", Identity.phoneId(ctx))
                    .put("manufacturer", Build.MANUFACTURER)
                    .put("model", Build.MODEL)
                    .put("android", Build.VERSION.RELEASE)
                    .put("full_access", MediaIndex.hasFullAccess(ctx))
                    .put("can_switch_usb", UsbDebug.canSwitch(ctx))
                    .toString(), keep)
                return keep
            }
            "POST /guard/alive" -> {
                UsbDebug.Guard.alive(ctx)
                Response.json(out, 200, """{"ok":true}""", keep)
                return keep
            }
            "POST /guard/end" -> {
                val off = runCatching { jsonBody(req).optBoolean("off", true) }.getOrDefault(true)
                // switched on by this app → always off again (a computer cannot keep it on)
                if (off || UsbDebug.Guard.switchedOnByApp(ctx)) UsbDebug.switchOff(ctx)
                else UsbDebug.Guard.reset(ctx)
                Response.json(out, 200, """{"ok":true}""", keep)
                return keep
            }
        }
        if (!MediaIndex.hasPermission(ctx)) {
            Response.json(out, 409, """{"error":"no permission for photos and videos - open the app on the phone"}""", keep)
            return keep
        }
        when ("${req.method} ${req.path}") {
            "GET /exists" -> Response.json(out, 200,
                JSONObject().put("exists", media.folderExists(req.query["path"] ?: "")).toString(), keep)
            "GET /folders" -> Response.json(out, 200,
                JSONArray(media.subfolders(req.query["path"] ?: "")).toString(), keep)
            "POST /list" -> {
                val arr = jsonBody(req).getJSONArray("folders")
                val folders = (0 until arr.length()).map { arr.getString(it) }
                onEvent("Computer ${pc.name} is reading the file list …")
                val res = JSONArray()
                media.list(folders).forEach {
                    res.put(JSONObject().put("rel", it.rel).put("size", it.size).put("mtime", it.mtime))
                }
                Response.json(out, 200, res.toString(), keep)
            }
            "POST /hashes" -> {
                val arr = jsonBody(req).getJSONArray("rels")
                val res = JSONObject()
                for (i in 0 until arr.length()) {
                    val rel = arr.getString(i)
                    val item = media.find(rel) ?: continue
                    runCatching { media.sha256(item) }.onSuccess { res.put(rel, it) }
                }
                Response.json(out, 200, res.toString(), keep)
            }
            "GET /file" -> {
                val item = media.find(req.query["rel"] ?: "")
                if (item == null) {
                    Response.json(out, 404, """{"error":"not found"}""", keep)
                } else {
                    // the computer asks for every file (pull) - the phone only answers
                    onEvent("${pc.name} is copying ${item.rel.substringAfterLast('/')}")
                    media.open(item).use { Response.stream(out, it, item.size, keep) { lastActivity = System.currentTimeMillis() } }
                }
            }
            "POST /done" -> {
                Response.json(out, 200, """{"ok":true}""", false)
                onEvent("DONE")
                return false
            }
            else -> Response.json(out, 404, """{"error":"unknown request"}""", keep)
        }
        return keep
    }
}

object BuildConfigInfo {
    fun versionName(ctx: Context): String =
        runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "" }.getOrDefault("")
}

/** A computer asked to pair over the USB cable; the user accepts or refuses it on the phone. */
object CablePairing {
    enum class State { NONE, PENDING, ACCEPTED, REFUSED }
    private data class Req(val pcId: String, val name: String, val code: String, val created: Long, var state: State)
    @Volatile private var req: Req? = null
    var pendingName by androidx.compose.runtime.mutableStateOf<String?>(null)
        private set
    var pendingCode by androidx.compose.runtime.mutableStateOf("")
        private set

    /** false = another computer's (or app's) request is still waiting – it is never replaced. */
    @Synchronized fun request(pcId: String, name: String, code: String): Boolean {
        val r = req
        if (r != null && r.state == State.PENDING && r.pcId != pcId &&
            System.currentTimeMillis() - r.created < 5 * 60_000) return false
        req = Req(pcId, name, code, System.currentTimeMillis(), State.PENDING)
        pendingName = name
        pendingCode = code
        return true
    }

    @Synchronized fun state(pcId: String): State {
        val r = req ?: return State.NONE
        if (r.pcId != pcId) return State.NONE
        if (System.currentTimeMillis() - r.created > 5 * 60_000) { req = null; pendingName = null; return State.NONE }
        return r.state
    }

    @Synchronized fun answer(accept: Boolean) {
        req?.state = if (accept) State.ACCEPTED else State.REFUSED
        pendingName = null
        pendingCode = ""
    }

    /** Ends the request; returns the computer's name. */
    @Synchronized fun take(pcId: String): String? {
        val r = req ?: return null
        if (r.pcId != pcId) return null
        req = null
        return r.name
    }
}
