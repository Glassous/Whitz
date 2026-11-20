package com.glassous.whitz.core.storage

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.glassous.whitz.BuildConfig
import com.glassous.whitz.core.model.ThemePreference
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.network.WhitzJson
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class TokenStorage(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("whitz_secure_prefs", Context.MODE_PRIVATE)

    @Volatile
    var accessToken: String? = null
        private set

    @Volatile
    private var accessExpMs: Long? = null

    fun setAccessToken(token: String?) {
        accessToken = token
        accessExpMs = token?.let { parseJwtExpMs(it) }
    }

    fun isAccessTokenExpiringSoon(bufferMs: Long = 30_000L): Boolean {
        val tok = accessToken ?: return true
        if (tok.isBlank()) return true
        val exp = accessExpMs ?: return false
        return System.currentTimeMillis() >= exp - bufferMs
    }

    fun saveRefreshToken(token: String) {
        if (token.isBlank()) return
        val encrypted = encrypt(token)
        prefs.edit().putString(KEY_REFRESH_TOKEN, encrypted).apply()
    }

    fun getRefreshToken(): String? {
        val raw = prefs.getString(KEY_REFRESH_TOKEN, null) ?: return null
        return decrypt(raw)
    }

    fun saveUser(user: User) {
        val json = WhitzJson.encodeToString(User.serializer(), user)
        prefs.edit().putString(KEY_USER, json).apply()
    }

    fun getUser(): User? {
        val raw = prefs.getString(KEY_USER, null) ?: return null
        return try {
            WhitzJson.decodeFromString(User.serializer(), raw)
        } catch (_: Exception) {
            null
        }
    }

    fun hasStoredSession(): Boolean {
        return !getRefreshToken().isNullOrBlank() || getUser() != null
    }

    fun clearSession() {
        accessToken = null
        accessExpMs = null
        prefs.edit()
            .remove(KEY_REFRESH_TOKEN)
            .remove(KEY_USER)
            .apply()
    }

    fun getThemePreference(): ThemePreference {
        val name = prefs.getString(KEY_THEME, ThemePreference.SYSTEM.name)
        return ThemePreference.entries.firstOrNull { it.name == name } ?: ThemePreference.SYSTEM
    }

    fun setThemePreference(pref: ThemePreference) {
        prefs.edit().putString(KEY_THEME, pref.name).apply()
    }

    fun getApiBaseUrl(): String {
        val saved = prefs.getString(KEY_API_BASE_URL, null)?.trim()?.trimEnd('/')
        return if (!saved.isNullOrBlank()) saved else BuildConfig.API_BASE_URL.trimEnd('/')
    }

    fun setApiBaseUrl(url: String?) {
        val cleaned = url?.trim()?.trimEnd('/')
        if (cleaned.isNullOrBlank()) {
            prefs.edit().remove(KEY_API_BASE_URL).apply()
        } else {
            prefs.edit().putString(KEY_API_BASE_URL, cleaned).apply()
        }
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        val existing = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
        if (existing != null) return existing
        val keyGenerator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()
        keyGenerator.init(spec)
        return keyGenerator.generateKey()
    }

    private fun encrypt(plainText: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val iv = cipher.iv
        val cipherBytes = cipher.doFinal(plainText.toByteArray(Charsets.UTF_8))
        val combined = ByteArray(1 + iv.size + cipherBytes.size)
        combined[0] = iv.size.toByte()
        System.arraycopy(iv, 0, combined, 1, iv.size)
        System.arraycopy(cipherBytes, 0, combined, 1 + iv.size, cipherBytes.size)
        return Base64.encodeToString(combined, Base64.NO_WRAP)
    }

    private fun decrypt(encoded: String): String? {
        return try {
            val combined = Base64.decode(encoded, Base64.NO_WRAP)
            val ivLen = combined[0].toInt() and 0xFF
            val iv = combined.copyOfRange(1, 1 + ivLen)
            val cipherBytes = combined.copyOfRange(1 + ivLen, combined.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, iv))
            String(cipher.doFinal(cipherBytes), Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }

    private fun parseJwtExpMs(token: String): Long? {
        return try {
            val parts = token.split(".")
            if (parts.size != 3) return null
            val payloadBytes = Base64.decode(parts[1], Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
            val json = WhitzJson.parseToJsonElement(String(payloadBytes, Charsets.UTF_8))
            val exp = (json as? kotlinx.serialization.json.JsonObject)?.get("exp")
            val expSec = (exp as? kotlinx.serialization.json.JsonPrimitive)?.content?.toLongOrNull()
            expSec?.times(1000L)
        } catch (_: Exception) {
            null
        }
    }

    companion object {
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val KEY_ALIAS = "whitz_refresh_token_key"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val KEY_REFRESH_TOKEN = "refresh_token_enc"
        private const val KEY_USER = "user_json"
        private const val KEY_THEME = "theme_pref"
        private const val KEY_API_BASE_URL = "api_base_url"
    }
}
