package io.github.machetso.mediabackup

import android.content.Context
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
        Guard.armStart()
        return null
    }

    /** USB debugging and Wireless debugging off (the Developer options stay). */
    fun switchOff(context: Context): String? {
        if (!canSwitch(context)) return "Not allowed."
        put(context, "adb_wifi_enabled", 0)
        put(context, Settings.Global.ADB_ENABLED, 0)
        Guard.reset()
        return null
    }

    fun wirelessOff(context: Context) { if (canSwitch(context)) put(context, "adb_wifi_enabled", 0) }
    fun usbOff(context: Context) { if (canSwitch(context)) put(context, Settings.Global.ADB_ENABLED, 0) }

    object Guard {
        @Volatile private var startDeadline = 0L      // waiting for the backup start until …
        @Volatile private var lastAlive = 0L          // backup running: last "still here"
        @Volatile private var channel = ""
        var text by mutableStateOf("")                // shown on the screen
        val engaged get() = startDeadline != 0L || lastAlive != 0L

        fun armStart() {
            startDeadline = System.currentTimeMillis() + START_MS
            lastAlive = 0L
        }

        /** The computer started a backup. channel: "usb" | "wifi" | "wifi-adb". */
        fun backupStarted(context: Context, channel: String) {
            startDeadline = 0L
            lastAlive = System.currentTimeMillis()
            this.channel = channel
            when (channel) {
                "usb" -> wirelessOff(context)
                "wifi" -> { usbOff(context); wirelessOff(context) }
                "wifi-adb" -> usbOff(context)        // keeps Wireless debugging (tested, Pixel 10 Pro)
            }
        }

        fun alive() { if (lastAlive != 0L) lastAlive = System.currentTimeMillis() }

        fun reset() { startDeadline = 0L; lastAlive = 0L; text = "" }

        /** Every second. Returns a message when it switched debugging off. */
        fun tick(context: Context): String? {
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
                    switchOff(context)
                    return if (channel == "wifi") "Connection to the computer lost."
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
