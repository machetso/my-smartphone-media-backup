package io.github.machetso.mediabackup

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import org.json.JSONArray
import org.json.JSONObject
import java.math.BigInteger
import java.net.Socket
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.Principal
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import java.util.Date
import java.util.UUID
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLEngine
import javax.net.ssl.X509ExtendedKeyManager
import javax.security.auth.x500.X500Principal

/**
 * The phone's TLS identity (key never leaves the Android Keystore) and the list of paired
 * computers. The computer pins the certificate's SHA-256 fingerprint when pairing.
 */
object Identity {
    private const val ALIAS = "phonebackup-tls"
    private const val PREFS = "identity"

    private fun keyStore(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    @Synchronized
    fun ensureKey() {
        val ks = keyStore()
        if (ks.containsAlias(ALIAS)) return
        val gen = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
        val now = System.currentTimeMillis()
        gen.initialize(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256,
                    KeyProperties.DIGEST_SHA384, KeyProperties.DIGEST_SHA512)
                .setCertificateSubject(X500Principal("CN=PhoneBackup Companion"))
                .setCertificateSerialNumber(BigInteger.valueOf(now))
                .setCertificateNotBefore(Date(now - 86_400_000L))
                .setCertificateNotAfter(Date(now + 30L * 365 * 86_400_000L))
                .build()
        )
        gen.generateKeyPair()
    }

    fun certificate(): X509Certificate {
        ensureKey()
        return keyStore().getCertificate(ALIAS) as X509Certificate
    }

    private fun privateKey(): PrivateKey {
        ensureKey()
        return keyStore().getKey(ALIAS, null) as PrivateKey
    }

    fun fingerprint(): String = sha256Hex(certificate().encoded)

    fun sslContext(): SSLContext {
        val cert = certificate()
        val key = privateKey()
        val km = object : X509ExtendedKeyManager() {
            override fun getClientAliases(keyType: String?, issuers: Array<out Principal>?) = null
            override fun chooseClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, socket: Socket?) = null
            override fun getServerAliases(keyType: String?, issuers: Array<out Principal>?) = arrayOf(ALIAS)
            override fun chooseServerAlias(keyType: String?, issuers: Array<out Principal>?, socket: Socket?) =
                if (keyType == null || keyType.startsWith("EC")) ALIAS else null
            override fun chooseEngineServerAlias(keyType: String?, issuers: Array<out Principal>?, engine: SSLEngine?) =
                chooseServerAlias(keyType, issuers, null)
            override fun getCertificateChain(alias: String?) = arrayOf(cert)
            override fun getPrivateKey(alias: String?) = key
        }
        return SSLContext.getInstance("TLS").apply { init(arrayOf(km), null, SecureRandom()) }
    }

    // ------------------------------------------------------------------ phone id, paired computers
    fun phoneId(ctx: Context): String {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return p.getString("phone_id", null) ?: UUID.randomUUID().toString().also {
            p.edit().putString("phone_id", it).apply()
        }
    }

    data class Computer(val id: String, val name: String, val secret: String, val paired: Long)

    fun computers(ctx: Context): List<Computer> {
        val raw = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("computers", "[]")
        val arr = JSONArray(raw)
        return (0 until arr.length()).map {
            val o = arr.getJSONObject(it)
            Computer(o.getString("id"), o.getString("name"), o.getString("secret"), o.optLong("paired"))
        }
    }

    private fun saveComputers(ctx: Context, list: List<Computer>) {
        val arr = JSONArray()
        list.forEach {
            arr.put(JSONObject().put("id", it.id).put("name", it.name).put("secret", it.secret).put("paired", it.paired))
        }
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("computers", arr.toString()).apply()
    }

    @Synchronized
    fun addComputer(ctx: Context, id: String, name: String): String {
        val bytes = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val secret = bytes.joinToString("") { "%02x".format(it) }
        val list = computers(ctx).filter { it.id != id } + Computer(id, name, secret, System.currentTimeMillis())
        saveComputers(ctx, list)
        return secret
    }

    @Synchronized
    fun removeComputer(ctx: Context, id: String) = saveComputers(ctx, computers(ctx).filter { it.id != id })

    /** The paired computer that uses this secret, or null. Constant-time comparison. */
    fun computerFor(ctx: Context, secret: String?): Computer? {
        if (secret.isNullOrEmpty()) return null
        return computers(ctx).firstOrNull { MessageDigest.isEqual(it.secret.toByteArray(), secret.toByteArray()) }
    }

    fun sha256Hex(b: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

    /** 6-digit code shown on phone AND computer while pairing - must be the same on both. */
    fun pairingCode(token: String, fingerprint: String): String {
        val d = MessageDigest.getInstance("SHA-256").digest("$token:$fingerprint".toByteArray())
        val n = ((d[0].toLong() and 0xff) shl 24) or ((d[1].toLong() and 0xff) shl 16) or
            ((d[2].toLong() and 0xff) shl 8) or (d[3].toLong() and 0xff)
        return "%06d".format(n % 1_000_000)
    }
}
