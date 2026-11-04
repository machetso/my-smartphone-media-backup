package io.github.machetso.mediabackup

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/** Shared state for the screen. */
object AppState {
    var running by mutableStateOf(false)
    var port by mutableStateOf(0)
    var status by mutableStateOf("")
    var pairedChanged by mutableStateOf(0)
}

/**
 * "Backup mode": runs the read-only server while the computer copies, keeps Wi-Fi and CPU awake,
 * announces the phone anonymously (mDNS _phonebkp._tcp + Bluetooth LE, see Announce) and runs the
 * USB-debugging guard (see UsbDebug). Stops by itself when the computer
 * says the backup is done, or after 30 minutes without any request.
 */
class BackupService : Service() {
    companion object {
        const val SERVICE_TYPE = "_phonebkp._tcp"
        private const val CHANNEL = "backup"
        private const val IDLE_MS = 30 * 60_000L
        @Volatile var server: Server? = null
            private set

        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, BackupService::class.java))
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, BackupService::class.java))
        }
    }

    private var wake: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private val main = Handler(Looper.getMainLooper())
    private val idleCheck = object : Runnable {
        override fun run() {
            val s = server ?: return
            if (System.currentTimeMillis() - s.lastActivity > IDLE_MS) {
                stopSelf()
                return
            }
            main.postDelayed(this, 60_000)
        }
    }
    // every second: debugging guard (UsbDebug) + anonymous announcement (new token every 10 min)
    private val tick = object : Runnable {
        override fun run() {
            UsbDebug.Guard.tick(this@BackupService)?.let { AppState.status = it; notify(it) }
            server?.let { Announce.refresh(this@BackupService, it.port) }
            main.postDelayed(this, 1000)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Backup mode", NotificationManager.IMPORTANCE_LOW))
        val n = notification("Waiting for the computer – photos and videos are shared read-only.")
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(1, n)
        }
        wake = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "phonebackup:server").apply { acquire(4 * 3600_000L) }
        @Suppress("DEPRECATION")
        wifiLock = (applicationContext.getSystemService(WIFI_SERVICE) as WifiManager)
            .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "phonebackup:wifi").apply { acquire() }

        val srv = Server(this) { ev -> main.post { onServerEvent(ev) } }
        try {
            srv.start()
        } catch (e: Exception) {
            AppState.status = "Could not start: ${e.message}"
            stopSelf()
            return
        }
        server = srv
        AppState.running = true
        AppState.port = srv.port
        AppState.status = "Waiting for the computer …"
        Announce.refresh(this, srv.port)
        main.postDelayed(idleCheck, 60_000)
        main.postDelayed(tick, 1000)
    }

    private fun onServerEvent(ev: String) {
        if (ev == "DONE") {
            AppState.status = "Backup finished – backup mode switched off."
            stopSelf()
            return
        }
        if (ev == "PAIR_REQUEST") {
            val t = "${CablePairing.pendingName ?: "A computer"} wants to pair over the USB cable – open the app to confirm."
            AppState.status = t
            notify(t)
            startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return
        }
        if (ev.startsWith("Paired")) {
            AppState.pairedChanged++
            Announce.stop(this)                    // announce the new computer's token too
        }
        AppState.status = ev
        notify(ev)
    }

    private fun notify(text: String) =
        getSystemService(NotificationManager::class.java).notify(1, notification(text))

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("Backup mode on")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        Announce.stop(this)
        if (UsbDebug.Guard.engaged) UsbDebug.switchOff(this)     // backup mode ends → debugging off
        server?.stop()
        server = null
        runCatching { wifiLock?.release() }
        runCatching { if (wake?.isHeld == true) wake?.release() }
        AppState.running = false
        AppState.port = 0
        if (!AppState.status.startsWith("Backup finished")) AppState.status = "Backup mode is off."
        super.onDestroy()
    }
}
