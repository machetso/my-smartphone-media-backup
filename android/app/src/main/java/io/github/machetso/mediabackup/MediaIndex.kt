package io.github.machetso.mediabackup

import android.Manifest
import android.content.ContentUris
import android.content.pm.PackageManager
import android.os.Build
import android.content.Context
import android.net.Uri
import android.provider.MediaStore
import java.io.InputStream
import java.security.MessageDigest

/**
 * Photos and videos of the phone's shared storage, read through MediaStore (read-only).
 * Paths are the same as over ADB ("DCIM/Camera/PXL_….jpg", relative to /sdcard), so a backup
 * made over ADB and one made with this app are the same backup.
 */
class MediaIndex(private val ctx: Context) {
    companion object {
        val PERMISSIONS: Array<String> =
            if (Build.VERSION.SDK_INT >= 33) arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO)
            else arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)

        /** Full access to all photos and videos (not only "selected photos" on Android 14+). */
        fun hasFullAccess(ctx: Context) = PERMISSIONS.all {
            ctx.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
        }

        fun hasPermission(ctx: Context) = hasFullAccess(ctx)

        /** Android 17+: talking to devices in the local network (the computer) needs a permission. */
        const val LOCAL_NETWORK = "android.permission.ACCESS_LOCAL_NETWORK"

        fun needsLocalNetwork() = Build.VERSION.SDK_INT >= 37

        fun hasLocalNetwork(ctx: Context) = !needsLocalNetwork() ||
            ctx.checkSelfPermission(LOCAL_NETWORK) == PackageManager.PERMISSION_GRANTED
    }

    data class Item(val rel: String, val size: Long, val mtime: Long, val uri: Uri)

    private var cache: Map<String, Item> = emptyMap()
    private var cacheTime = 0L

    // The list is kept for the whole backup (rebuilding it takes seconds with thousands of photos
    // and blocked every request): /list builds it fresh, a file that is not found rebuilds it once.
    @Synchronized
    fun all(maxAgeMs: Long = 10 * 60_000L): Map<String, Item> {
        if (System.currentTimeMillis() - cacheTime > maxAgeMs) {
            cache = scan()
            cacheTime = System.currentTimeMillis()
        }
        return cache
    }

    private fun scan(): Map<String, Item> {
        val res = HashMap<String, Item>()
        val vol = MediaStore.VOLUME_EXTERNAL_PRIMARY
        for (col in listOf(MediaStore.Images.Media.getContentUri(vol), MediaStore.Video.Media.getContentUri(vol))) {
            val proj = arrayOf(
                MediaStore.MediaColumns._ID, MediaStore.MediaColumns.RELATIVE_PATH,
                MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE,
                MediaStore.MediaColumns.DATE_MODIFIED,
            )
            ctx.contentResolver.query(col, proj, "${MediaStore.MediaColumns.IS_PENDING} = 0", null, null)?.use { c ->
                while (c.moveToNext()) {
                    val dir = c.getString(1) ?: continue
                    val name = c.getString(2) ?: continue
                    val rel = (dir.trimEnd('/') + "/" + name).trimStart('/')
                    if (rel.split('/').any { it.startsWith(".") }) continue      // hidden, like ADB mode
                    res[rel] = Item(rel, c.getLong(3), c.getLong(4), ContentUris.withAppendedId(col, c.getLong(0)))
                }
            }
        }
        return res
    }

    fun folderExists(rel: String): Boolean {
        val p = rel.trim('/') + "/"
        return all().keys.any { it.startsWith(p) }
    }

    /** Direct sub folders of [rel] that contain photos/videos (anywhere below). */
    fun subfolders(rel: String): List<String> {
        val p = rel.trim('/').let { if (it.isEmpty()) "" else "$it/" }
        val out = sortedSetOf<String>()
        for (k in all().keys) {
            if (!k.startsWith(p)) continue
            val rest = k.substring(p.length)
            val i = rest.indexOf('/')
            if (i > 0) out.add(p + rest.substring(0, i))
        }
        return out.toList()
    }

    fun list(folders: List<String>): List<Item> {
        val prefixes = folders.map { it.trim('/') + "/" }
        return all(0).values.filter { item -> prefixes.any { item.rel.startsWith(it) } }.sortedBy { it.rel }
    }

    fun find(rel: String): Item? = all()[rel] ?: synchronized(this) {
        if (System.currentTimeMillis() - cacheTime > 3_000) all(0)[rel] else null
    }

    fun open(item: Item): InputStream =
        ctx.contentResolver.openInputStream(item.uri) ?: throw java.io.FileNotFoundException(item.rel)

    fun sha256(item: Item): String {
        val md = MessageDigest.getInstance("SHA-256")
        open(item).use { inp ->
            val buf = ByteArray(1 shl 20)
            while (true) {
                val n = inp.read(buf)
                if (n < 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }
}
