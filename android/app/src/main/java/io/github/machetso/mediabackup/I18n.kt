package io.github.machetso.mediabackup

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import org.json.JSONObject
import java.text.DecimalFormatSymbols
import java.util.Locale

/**
 * User interface languages (copied from VideoSpeedControl). Texts stay English in the code – `tr("Start backup mode")` –
 * and are looked up in one dictionary per language: `i18n/<code>.json` at the top of the
 * repository (packed into the app's assets, shared with the desktop program):
 *
 *     { "language": "Deutsch", "locale": "de-DE", "rtl": false,
 *       "texts": { "Start backup mode": "Sicherungsmodus starten",
 *                  "%d files": { "one": "%d Datei", "other": "%d Dateien" } } }
 *
 * A new language = a new file; the menu lists every file found. Default = the phone's language
 * if there is a dictionary for it, else English; the choice (pref "lang") is kept. Templates use
 * String.format placeholders; numbers follow the language's locale. [choice] is Compose state,
 * so switching redraws every text at once.
 */
object I18n {
    class Language(val code: String, val name: String, val locale: Locale, val rtl: Boolean,
                   val texts: Map<String, Any>)        // value: String, or Map of plural forms

    const val SYSTEM = "system"
    private const val PREFS = "ui"
    val ENGLISH = Language("en", "English", Locale.US, false, emptyMap())

    var languages: List<Language> = listOf(ENGLISH)
        private set
    var choice by mutableStateOf(SYSTEM)
        private set

    /** The language in use. */
    val current: Language
        get() = languages.firstOrNull { it.code == choice } ?: phoneLanguage ?: ENGLISH

    /** The phone's language, if there is a dictionary for it. */
    val phoneLanguage: Language?
        get() {
            val code = when (val l = Locale.getDefault().language) { "iw" -> "he"; "in" -> "id"; "ji" -> "yi"; else -> l }
            return languages.firstOrNull { it.code == code }
        }

    val german: Boolean get() = current.code == "de"
    val locale: Locale get() = current.locale
    val decimal: Char get() = DecimalFormatSymbols.getInstance(locale).decimalSeparator

    /** Reads the dictionaries (once) and the stored choice. */
    fun load(context: Context) {
        if (languages.size == 1) {
            val files = context.assets.list("")?.filter { it.endsWith(".json") } ?: emptyList()
            useDictionaries(files.mapNotNull { f ->
                runCatching { f.removeSuffix(".json") to context.assets.open(f).use { it.readBytes().decodeToString() } }.getOrNull()
            })
        }
        choice = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("lang", SYSTEM) ?: SYSTEM
    }

    /** [files]: (code, JSON text) – the app's assets, or the repository folder in tests. */
    fun useDictionaries(files: List<Pair<String, String>>) {
        val parsed = files.mapNotNull { (code, text) -> runCatching { parse(code, text) }.getOrNull() }
        languages = (listOf(ENGLISH) + parsed.filter { it.code != "en" }).sortedBy { if (it.code == "en") "" else it.name }
    }

    private fun parse(code: String, text: String): Language {
        val o = JSONObject(text)
        val t = o.getJSONObject("texts")
        val texts = HashMap<String, Any>()
        for (k in t.keys()) {
            val v = t.get(k)
            texts[k] = if (v is JSONObject) v.keys().asSequence().associateWith { v.getString(it) } else v.toString()
        }
        return Language(code, o.getString("language"), Locale.forLanguageTag(o.optString("locale", code)),
            o.optBoolean("rtl", false), texts)
    }

    fun choose(context: Context, code: String) {
        choice = code
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("lang", code).apply()
    }

    /** Without storing it (tests). */
    fun use(code: String) { choice = code }

    /** CLDR plural category of [n] (the cases the dictionaries need). */
    fun pluralCategory(code: String, n: Long): String = when (code) {
        "fr" -> if (n == 0L || n == 1L) "one" else "other"
        "he" -> when (n) { 1L -> "one"; 2L -> "two"; else -> "other" }
        "ro" -> when { n == 1L -> "one"; n == 0L || n % 100 in 1..19 -> "few"; else -> "other" }
        "tlh", "ja", "zh", "ko" -> "other"
        else -> if (n == 1L) "one" else "other"
    }
}

/** [en] in the current language; with [args] it is a String.format template. */
fun tr(en: String, vararg args: Any?): String {
    val text = when (val v = I18n.current.texts[en]) {
        is String -> v
        is Map<*, *> -> (v["other"] ?: en).toString()
        else -> en
    }
    return if (args.isEmpty()) text else format(text, args)
}

private val PLACEHOLDER = Regex("%[0-9.]*[sdf]")

/**
 * String.format in the language's locale. Right-to-left languages: every inserted value is
 * wrapped in Unicode isolates (FSI … PDI), so "4.0 s" or a file name stays one left-to-right run
 * inside Hebrew text instead of being torn apart by the bidi algorithm.
 */
private fun format(template: String, args: Array<out Any?>): String {
    val t = if (I18n.current.rtl) template.replace(PLACEHOLDER) { "\u2068${it.value}\u2069" } else template
    return String.format(I18n.locale, t, *args)
}

/**
 * Text with a number [n]: English [one] / [other]; the dictionaries key it by [other] and may give
 * every plural form of their language ("one", "two", "other").
 */
fun trp(one: String, other: String, n: Number, vararg args: Any?): String {
    val lang = I18n.current
    val text = when (val v = lang.texts[other]) {
        is String -> v
        is Map<*, *> -> (v[I18n.pluralCategory(lang.code, n.toLong())] ?: v["other"] ?: other).toString()
        else -> if (n.toLong() == 1L) one else other
    }
    return format(text, args)
}
