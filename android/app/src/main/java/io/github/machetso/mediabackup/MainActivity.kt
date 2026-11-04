package io.github.machetso.mediabackup

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.concurrent.thread

class MainActivity : ComponentActivity() {
    private var hasAccess by mutableStateOf(false)
    private var hasNetwork by mutableStateOf(false)
    private var pairCode by mutableStateOf<String?>(null)
    private var pairInfo by mutableStateOf("")
    private var canSwitchUsb by mutableStateOf(false)
    private var usbInfo by mutableStateOf("")

    private val askMedia = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        refresh()
    }

    private fun refresh() {
        hasAccess = MediaIndex.hasFullAccess(this)
        hasNetwork = MediaIndex.hasLocalNetwork(this)
        canSwitchUsb = UsbDebug.canSwitch(this)
        if (hasNetwork) waitingPair?.let { startPairing(it) }
    }

    private fun askAll() {
        val list = MediaIndex.PERMISSIONS.toMutableList()
        if (MediaIndex.needsLocalNetwork()) list += MediaIndex.LOCAL_NETWORK
        if (Build.VERSION.SDK_INT >= 31) list += Manifest.permission.BLUETOOTH_ADVERTISE   // only to be found
        askMedia.launch(list.toTypedArray())
    }
    private val askNotify = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        refresh()
        if (!hasAccess || !hasNetwork) askAll()
        else if (Build.VERSION.SDK_INT >= 33) askNotify.launch(Manifest.permission.POST_NOTIFICATIONS)
        handle(intent)
        setContent {
            MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()) {
                Surface(Modifier.fillMaxSize()) { Screen() }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private var waitingPair: Pairing.Pending? = null

    private fun handle(intent: Intent?) {
        // the computer opened the app over the cable (pairing over USB / setup): start backup mode
        if (intent?.data?.scheme == "phonebackup" && intent.data?.host == "cable") {
            setIntent(Intent())
            BackupService.start(this)
            return
        }
        val p = intent?.data?.let { Pairing.parse(it) } ?: return
        setIntent(Intent())          // do not pair again on rotation
        pairCode = p.code
        if (!MediaIndex.hasLocalNetwork(this)) {
            waitingPair = p
            pairInfo = "Allow access to the local network first (button below)."
            return
        }
        startPairing(p)
    }

    private fun startPairing(p: Pairing.Pending) {
        waitingPair = null
        pairInfo = "Connecting to ${p.pcName} …"
        BackupService.start(this)
        thread {
            var tries = 0
            while (BackupService.server?.port.let { it == null || it == 0 } && tries++ < 50) Thread.sleep(100)
            val err = Pairing.announce(this, p, BackupService.server?.port ?: 0)
            runOnUiThread {
                pairInfo = err ?: "Check that ${p.pcName} shows the same code, then confirm there."
            }
        }
    }

    @Composable
    private fun Screen() {
        val running = AppState.running
        @Suppress("UNUSED_VARIABLE") val changed = AppState.pairedChanged
        val computers = Identity.computers(this)
        if (AppState.status.startsWith("Paired")) pairCode = null

        Column(
            Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("Fast Media Backup", fontSize = 26.sp, fontWeight = FontWeight.Bold)
            Text("Lets your computer back up the photos and videos of this phone. " +
                "The app can only READ photos and videos – it cannot delete or change anything. " +
                "If the computer set it up, it can also switch USB debugging on for a backup over the cable.",
                style = MaterialTheme.typography.bodyMedium)

            if (!hasAccess) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Access to photos and videos needed", fontWeight = FontWeight.SemiBold)
                        Text("Choose “Allow all” – with “Select photos” only the chosen ones could be backed up.")
                        Button(onClick = { askAll() }) { Text("Allow access") }
                    }
                }
            }
            if (!hasNetwork) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Access to the local network needed", fontWeight = FontWeight.SemiBold)
                        Text("Without it the computer cannot reach the phone (Android asks for " +
                            "“devices in the local network” / “Nearby devices”).")
                        Button(onClick = { askAll() }) { Text("Allow network access") }
                    }
                }
            }

            CablePairing.pendingName?.let { name ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Pair over the USB cable", fontWeight = FontWeight.SemiBold)
                        Text("“$name” wants to back up this phone. Only confirm if this phone is " +
                            "connected to that computer with a cable right now.")
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { CablePairing.answer(true) }) { Text("Pair") }
                            OutlinedButton(onClick = { CablePairing.answer(false) }) { Text("Refuse") }
                        }
                    }
                }
            }

            pairCode?.let { code ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Pairing", fontWeight = FontWeight.SemiBold)
                        Text(code.chunked(3).joinToString(" "), fontSize = 40.sp,
                            fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                        Text(pairInfo)
                        TextButton(onClick = { Pairing.cancel(); pairCode = null }) { Text("Cancel") }
                    }
                }
            }

            if (canSwitchUsb) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Backup over cable (fastest)", fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
                        Text("Switches USB debugging on for the backup. Then plug in the USB cable – " +
                            "the computer switches USB debugging off again when the backup is done.",
                            style = MaterialTheme.typography.bodyMedium)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = {
                                usbInfo = UsbDebug.switchOn(this@MainActivity)
                                    ?: "USB debugging is on – plug in the cable now."
                                BackupService.start(this@MainActivity)     // runs the 5-minute guard
                            }) { Text("Allow backup over cable") }
                            OutlinedButton(onClick = {
                                usbInfo = UsbDebug.switchOff(this@MainActivity) ?: "USB debugging is off."
                            }) { Text("Switch off") }
                        }
                        if (usbInfo.isNotEmpty()) Text(usbInfo, style = MaterialTheme.typography.bodySmall)
                        if (UsbDebug.Guard.text.isNotEmpty()) Text(UsbDebug.Guard.text, fontWeight = FontWeight.SemiBold)
                    }
                }
            }

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(if (running) "Backup mode is ON" else "Backup mode is off",
                        fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
                    if (AppState.status.isNotEmpty()) Text(AppState.status)
                    if (running) {
                        Text("Phone address: ${Announce.wifiAddress(this@MainActivity)?.hostAddress ?: "no network"}  ·  port ${AppState.port}",
                            style = MaterialTheme.typography.bodySmall)
                        Text("Start the backup on the computer – it asks the phone for each file and copies it; " +
                            "the phone sends nothing by itself. Backup mode switches off by itself when the " +
                            "backup is done, or after 5 minutes without use" +
                            (if (AppState.idleLeft.isNotEmpty()) " (in ${AppState.idleLeft})." else "."),
                            style = MaterialTheme.typography.bodySmall)
                        OutlinedButton(onClick = { BackupService.stop(this@MainActivity) }) { Text("Switch off") }
                    } else {
                        Button(enabled = hasAccess && hasNetwork && computers.isNotEmpty(),
                            onClick = { BackupService.start(this@MainActivity) }) { Text("Start backup mode") }
                        if (computers.isEmpty()) Text("Not paired yet: on the computer click " +
                            "“Set up phone app…” and scan the QR code.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            if (computers.isNotEmpty()) {
                Text("Paired computers", fontWeight = FontWeight.SemiBold)
                computers.forEach { pc ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(pc.name, Modifier.weight(1f))
                        TextButton(onClick = {
                            Identity.removeComputer(this@MainActivity, pc.id)
                            AppState.pairedChanged++
                        }) { Text("Remove") }
                    }
                }
            }
            Spacer(Modifier.padding(8.dp))
            Text("Version ${BuildConfigInfo.versionName(this@MainActivity)}", style = MaterialTheme.typography.bodySmall)
        }
    }
}
