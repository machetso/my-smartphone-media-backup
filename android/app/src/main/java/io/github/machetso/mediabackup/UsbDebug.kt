package io.github.machetso.mediabackup

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.provider.Settings
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Switches USB debugging on for one backup over the cable, and off again (user request 2026-11-04).
 *
 * Needs WRITE_SECURE_SETTINGS, which only the computer program can give (once, over a USB
 * debugging connection: `pm grant`). Android hides the real state from apps, so the app never
 * reads it - it only switches.
 *
 * Rules (Guard, checked every second while backup mode runs):
 * - 5 minutes after "Allow backup over cable" without a backup start → off.
 * - During a backup the computer says "still here" every 30 s; nothing for 2 minutes → off.
 * - Backup mode ends (finished, switched off, stopped) while the guard is on → off.
 * - One connection per backup: over the cable → Wireless debugging off; over Wireless debugging
 *   → USB debugging off; through this app over Wi-Fi → both off.
 *
 * The guard is saved (SharedPreferences) and backed by an alarm, so it survives an app update,
 * the app being killed and a reboot: USB debugging must never stay on by accident (fix 2026-11-05).
 */
object UsbDebug {
    private const val PERMISSION = "android.permission.WRITE_SECURE_SETTINGS"
    const val START_MS = 5 * 60_000L
    const val ALIVE_MS = 2 * 60_000L

    fun canSwitch(context: Context): Boolean =
        context.checkSelfPermission(PERMISSION) == PackageManager.PERMISSION_GRANTED

    private fun put(context: Context, name: String, value: Int): Boolean = try {
        Settings.Global.putInt(context.contentResolver, name, value)
        true
    } catch (e: SecurityException) {
        false
    }

    /** Developer options + USB debugging on. Returns an error text or null. */
    fun switchOn(context: Context): String? {
        if (!canSwitch(context)) return "Not allowed yet – connect the phone once with USB debugging switched on by hand."
        put(context, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 1)
        put(context, Settings.Global.ADB_ENABLED, 1)
        Guard.markSwitchedOn(context, true)
        Guard.armStart(context)
        return null
    }

    /** USB debugging and Wireless debugging off (the Developer options stay). */
    fun switchOff(context: Context): String? {
        if (!canSwitch(context)) return "Not allowed."
        put(context, "adb_wifi_enabled", 0)
        put(context, Settings.Global.ADB_ENABLED, 0)
        Guard.markSwitchedOn(context, false)
        Guard.reset(context)
        return null
    }

    fun wirelessOff(context: Context) { if (canSwitch(context)) put(context, "adb_wifi_enabled", 0) }
    fun usbOff(context: Context) { if (canSwitch(context)) put(context, Settings.Global.ADB_ENABLED, 0) }

    object Guard {
        private const val PREFS = "usb_guard"
        @Volatile private var startDeadline = 0L      // waiting for the backup start until …
        @Volatile private var lastAlive = 0L          // backup running: last "still here"
        @Volatile private var channel = ""
        @Volatile private var loaded = false
        var text by mutableStateOf("")                // shown on the screen
        val engaged get() = startDeadline != 0L || lastAlive != 0L

        /** Load the saved guard once per process (after an update, a kill or a reboot). */
        fun restore(context: Context) {
            if (loaded) return
            val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            startDeadline = p.getLong("start", 0L)
            lastAlive = p.getLong("alive", 0L)
            channel = p.getString("channel", "") ?: ""
            loaded = true
        }

        private fun save(context: Context) {
            loaded = true
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putLong("start", startDeadline).putLong("alive", lastAlive).putString("channel", channel)
                .apply()
            schedule(context)
        }

        /** Alarm at the next moment the guard may have to switch off (works without the app running). */
        fun schedule(context: Context) {
            val am = context.getSystemService(AlarmManager::class.java) ?: return
            val pi = PendingIntent.getBroadcast(context, 0, Intent(context, GuardReceiver::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val at = when {
                startDeadline != 0L -> startDeadline
                lastAlive != 0L -> lastAlive + ALIVE_MS
                else -> { am.cancel(pi); return }
            }
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at + 1000, pi)
        }

        /** Did THIS app switch USB debugging on? Then the end of a backup always switches it off. */
        fun switchedOnByApp(context: Context): Boolean =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("by_app", false)

        fun markSwitchedOn(context: Context, on: Boolean) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("by_app", on).apply()
        }

        fun armStart(context: Context) {
            startDeadline = System.currentTimeMillis() + START_MS
            lastAlive = 0L
            save(context)
        }

        /** The computer started a backup. channel: "usb" | "wifi" | "wifi-adb". */
        fun backupStarted(context: Context, channel: String) {
            startDeadline = 0L
            lastAlive = System.currentTimeMillis()
            this.channel = channel
            save(context)
            when (channel) {
                "usb" -> wirelessOff(context)
                "wifi" -> { usbOff(context); wirelessOff(context) }
                "wifi-adb" -> usbOff(context)        // keeps Wireless debugging (tested, Pixel 10 Pro)
            }
        }

        fun alive(context: Context) {
            if (lastAlive != 0L) { lastAlive = System.currentTimeMillis(); save(context) }
        }

        fun reset(context: Context) {
            startDeadline = 0L; lastAlive = 0L; channel = ""; text = ""
            save(context)
        }

        /** Every second (and from the alarm). Returns a message when it switched debugging off. */
        fun tick(context: Context): String? {
            restore(context)
            val now = System.currentTimeMillis()
            if (startDeadline != 0L) {
                val left = startDeadline - now
                if (left <= 0) {
                    switchOff(context)
                    return "No backup started within 5 minutes – USB debugging switched off."
                }
                text = "USB debugging switches off in %d:%02d if no backup starts.".format(left / 60_000, left / 1000 % 60)
            } else if (lastAlive != 0L) {
                if (now - lastAlive > ALIVE_MS) {
                    val wifi = channel == "wifi"
                    switchOff(context)
                    return if (wifi) "Connection to the computer lost."
                    else "Connection to the computer lost – USB debugging switched off."
                }
                text = if (channel == "wifi") "Backup over Wi-Fi running."
                else "Backup running – USB debugging switches off when it is done."
            } else {
                text = ""
            }
            return null
        }
    }
}

/**
 * Wakes the guard without the app running: the guard's alarm, after an app update
 * (MY_PACKAGE_REPLACED) and after a reboot (BOOT_COMPLETED). Switches debugging off when the
 * time is up, otherwise sets the alarm again.
 */
class GuardReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val g = UsbDebug.Guard
        g.restore(context)
        if (!g.engaged) return
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            // after a reboot no backup can be running any more
            UsbDebug.switchOff(context)
            return
        }
        if (g.tick(context) == null) g.schedule(context)       // not due yet: alarm again
    }
}
