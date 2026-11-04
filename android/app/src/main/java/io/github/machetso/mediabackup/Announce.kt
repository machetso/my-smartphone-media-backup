package io.github.machetso.mediabackup

import android.Manifest
import android.bluetooth.BluetoothManager
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import java.net.Inet4Address
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Anonymous announcement while backup mode is on (user request 2026-11-04).
 *
 * Nothing that identifies the phone is sent: no model, no fixed id. Per paired computer a 6-byte
 * token = HMAC-SHA256(secret, "fmb-announce:<window>") changes every 10 minutes; only a computer
 * that knows the secret recognises it. Then the computer verifies the phone's key over TLS.
 *
 * - Wi-Fi (mDNS / NSD): random service name, TXT "t" = tokens (hex, joined by ".").
 * - Bluetooth LE (ONLY to find the phone, never for files): manufacturer data, company 0xFFFF,
 *   "FB" + version 1 + per computer (max. 2) token(6) + IPv4(4) + port(2), address and port
 *   XOR-ed with HMAC(secret, "fmb-addr:<window>").
 * Same format in phonebackup/companion.py.
 */
object Announce {
    const val WINDOW_S = 600L
    const val COMPANY_ID = 0xFFFF
    private const val VERSION: Byte = 1

    fun window(nowMs: Long = System.currentTimeMillis()) = nowMs / 1000 / WINDOW_S

    private fun hmac(secret: String, msg: String): ByteArray =
        Mac.getInstance("HmacSHA256").run {
            init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
            doFinal(msg.toByteArray(Charsets.UTF_8))
        }

    fun token(secret: String, w: Long): ByteArray = hmac(secret, "fmb-announce:$w").copyOf(6)
    private fun addrMask(secret: String, w: Long): ByteArray = hmac(secret, "fmb-addr:$w").copyOf(6)

    fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }

    fun wifiAddress(ctx: Context): Inet4Address? {
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        val lp = cm.getLinkProperties(cm.activeNetwork) ?: return null
        return lp.linkAddresses.map { it.address }.firstOrNull { it is Inet4Address && !it.isLoopbackAddress } as Inet4Address?
    }

    /** Newest paired computers first (the BLE packet has room for two). */
    private fun secrets(ctx: Context) = Identity.computers(ctx).sortedByDescending { it.paired }.map { it.secret }

    fun nsdInfo(ctx: Context, port: Int, w: Long): NsdServiceInfo = NsdServiceInfo().apply {
        val rnd = ByteArray(4).also { SecureRandom().nextBytes(it) }
        serviceName = "FMB-${hex(rnd)}"
        serviceType = BackupService.SERVICE_TYPE
        setPort(port)
        setAttribute("v", "2")
        setAttribute("t", secrets(ctx).take(16).joinToString(".") { hex(token(it, w)) })
    }

    fun bleData(ctx: Context, port: Int, w: Long): ByteArray? {
        val ip = wifiAddress(ctx)?.address ?: byteArrayOf(0, 0, 0, 0)
        val list = secrets(ctx).take(2)
        if (list.isEmpty()) return null
        val out = java.io.ByteArrayOutputStream()
        out.write('F'.code); out.write('B'.code); out.write(VERSION.toInt())
        for (s in list) {
            out.write(token(s, w))
            val mask = addrMask(s, w)
            val plain = ip + byteArrayOf((port shr 8).toByte(), port.toByte())
            out.write(ByteArray(6) { (plain[it].toInt() xor mask[it].toInt()).toByte() })
        }
        return out.toByteArray()
    }

    // ------------------------------------------------------------------ running announcement
    private var nsdListener: NsdManager.RegistrationListener? = null
    private var bleCallback: AdvertiseCallback? = null
    private var currentWindow = -1L

    fun canAdvertise(ctx: Context) = Build.VERSION.SDK_INT < 31 ||
        ctx.checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) == PackageManager.PERMISSION_GRANTED

    /** Call every few seconds while backup mode runs: (re)announces when the window changes. */
    @Synchronized
    fun refresh(ctx: Context, port: Int) {
        val w = window()
        if (w == currentWindow) return
        stop(ctx)
        currentWindow = w
        val nsd = ctx.getSystemService(Context.NSD_SERVICE) as NsdManager
        val l = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(i: NsdServiceInfo) {}
            override fun onRegistrationFailed(i: NsdServiceInfo, code: Int) {}
            override fun onServiceUnregistered(i: NsdServiceInfo) {}
            override fun onUnregistrationFailed(i: NsdServiceInfo, code: Int) {}
        }
        runCatching { nsd.registerService(nsdInfo(ctx, port, w), NsdManager.PROTOCOL_DNS_SD, l); nsdListener = l }
        startBle(ctx, port, w)
    }

    @Suppress("MissingPermission")
    private fun startBle(ctx: Context, port: Int, w: Long) {
        if (!canAdvertise(ctx)) return
        val data = bleData(ctx, port, w) ?: return
        val adv = ctx.getSystemService(BluetoothManager::class.java)?.adapter
            ?.takeIf { it.isEnabled }?.bluetoothLeAdvertiser ?: return
        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_BALANCED)
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
            .setConnectable(false)
            .build()
        val ad = AdvertiseData.Builder()
            .setIncludeDeviceName(false)
            .setIncludeTxPowerLevel(false)
            .addManufacturerData(COMPANY_ID, data)
            .build()
        val cb = object : AdvertiseCallback() {}
        runCatching { adv.startAdvertising(settings, ad, cb); bleCallback = cb }
    }

    @Synchronized
    @Suppress("MissingPermission")
    fun stop(ctx: Context) {
        nsdListener?.let { l ->
            runCatching { (ctx.getSystemService(Context.NSD_SERVICE) as NsdManager).unregisterService(l) }
        }
        nsdListener = null
        bleCallback?.let { cb ->
            runCatching {
                ctx.getSystemService(BluetoothManager::class.java)?.adapter?.bluetoothLeAdvertiser?.stopAdvertising(cb)
            }
        }
        bleCallback = null
        currentWindow = -1L
    }
}
