package io.github.machetso.mediabackup

import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.URLDecoder

/** Minimal HTTP/1.1 (keep-alive, Content-Length bodies only) - enough for the backup protocol. */
class Request(
    val method: String,
    val path: String,
    val query: Map<String, String>,
    val headers: Map<String, String>,
    val body: ByteArray,
) {
    val keepAlive get() = headers["connection"]?.lowercase() != "close"

    companion object {
        private const val MAX_HEADER = 16 * 1024
        private const val MAX_BODY = 2L * 1024 * 1024     // was 64 MB – allocated before any check

        /** null = connection closed cleanly. */
        fun read(inp: BufferedInputStream): Request? {
            val head = ByteArrayOutputStream()
            var last4 = 0
            while (true) {
                val b = inp.read()
                if (b < 0) {
                    if (head.size() == 0) return null
                    throw java.io.EOFException("connection closed in header")
                }
                head.write(b)
                last4 = (last4 shl 8) or b
                if (last4 == 0x0d0a0d0a) break
                if (head.size() > MAX_HEADER) throw IllegalArgumentException("header too large")
            }
            val lines = head.toString(Charsets.ISO_8859_1.name()).split("\r\n")
            val parts = lines[0].split(" ")
            if (parts.size < 3) throw IllegalArgumentException("bad request line")
            val headers = HashMap<String, String>()
            for (l in lines.drop(1)) {
                val i = l.indexOf(':')
                if (i > 0) headers[l.substring(0, i).trim().lowercase()] = l.substring(i + 1).trim()
            }
            val len = headers["content-length"]?.toLongOrNull() ?: 0L
            if (len < 0 || len > MAX_BODY) throw IllegalArgumentException("body too large")
            val body = ByteArray(len.toInt())
            var off = 0
            while (off < body.size) {
                val n = inp.read(body, off, body.size - off)
                if (n < 0) throw java.io.EOFException("connection closed in body")
                off += n
            }
            val target = parts[1]
            val q = target.indexOf('?')
            val path = if (q >= 0) target.substring(0, q) else target
            val query = HashMap<String, String>()
            if (q >= 0) {
                for (kv in target.substring(q + 1).split('&')) {
                    if (kv.isEmpty()) continue
                    val e = kv.indexOf('=')
                    val k = URLDecoder.decode(if (e >= 0) kv.substring(0, e) else kv, "UTF-8")
                    val v = if (e >= 0) URLDecoder.decode(kv.substring(e + 1), "UTF-8") else ""
                    query[k] = v
                }
            }
            return Request(parts[0].uppercase(), path, query, headers, body)
        }
    }
}

object Response {
    private val REASON = mapOf(200 to "OK", 400 to "Bad Request", 401 to "Unauthorized",
        403 to "Forbidden", 404 to "Not Found", 409 to "Conflict", 500 to "Internal Server Error")

    fun head(out: OutputStream, status: Int, type: String, length: Long, keepAlive: Boolean) {
        val h = "HTTP/1.1 $status ${REASON[status] ?: "Status"}\r\n" +
            "Content-Type: $type\r\nContent-Length: $length\r\n" +
            "Connection: ${if (keepAlive) "keep-alive" else "close"}\r\n\r\n"
        out.write(h.toByteArray(Charsets.ISO_8859_1))
    }

    fun json(out: OutputStream, status: Int, json: String, keepAlive: Boolean) {
        val b = json.toByteArray(Charsets.UTF_8)
        head(out, status, "application/json; charset=utf-8", b.size.toLong(), keepAlive)
        out.write(b)
        out.flush()
    }

    fun stream(out: OutputStream, inp: InputStream, length: Long, keepAlive: Boolean, onBytes: (Int) -> Unit) {
        head(out, 200, "application/octet-stream", length, keepAlive)
        val buf = ByteArray(1 shl 18)
        var left = length
        while (left > 0) {
            val n = inp.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
            if (n < 0) throw java.io.EOFException("file shorter than announced")
            out.write(buf, 0, n)
            left -= n
            onBytes(n)
        }
        out.flush()
    }
}
