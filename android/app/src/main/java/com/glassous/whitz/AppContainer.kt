package com.glassous.whitz

import android.content.Context
import com.glassous.whitz.core.files.CosUploader
import com.glassous.whitz.core.model.OneHandedConfig
import com.glassous.whitz.core.model.OneHandedSide
import com.glassous.whitz.core.model.ThemePreference
import com.glassous.whitz.core.model.resolveServerAssetUrl
import com.glassous.whitz.core.network.AuthManager
import com.glassous.whitz.core.network.NetworkModule
import com.glassous.whitz.core.storage.ChatCacheStorage
import com.glassous.whitz.core.storage.TokenStorage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class AppContainer(context: Context) {
    val appContext: Context = context.applicationContext
    val storage = TokenStorage(appContext)
    val chatCache = ChatCacheStorage(appContext)
    val authManager = AuthManager(storage, onClearSession = { chatCache.clear() })
    val network = NetworkModule(storage, authManager)
    val cosUploader = CosUploader(network.cosOkHttpClient, appContext.contentResolver)

    private val _themePreference = MutableStateFlow(storage.getThemePreference())
    val themePreference: StateFlow<ThemePreference> = _themePreference.asStateFlow()

    private val _oneHandedConfig = MutableStateFlow(storage.getOneHandedConfig())
    val oneHandedConfig: StateFlow<OneHandedConfig> = _oneHandedConfig.asStateFlow()

    fun setThemePreference(pref: ThemePreference) {
        storage.setThemePreference(pref)
        _themePreference.value = pref
    }

    fun setOneHandedEnabled(enabled: Boolean) {
        storage.setOneHandedEnabled(enabled)
        _oneHandedConfig.value = _oneHandedConfig.value.copy(enabled = enabled)
    }

    fun setOneHandedSide(side: OneHandedSide) {
        storage.setOneHandedSide(side)
        _oneHandedConfig.value = _oneHandedConfig.value.copy(side = side)
    }

    fun resolveAssetUrl(pathOrUrl: String?): String? =
        resolveServerAssetUrl(storage.getApiBaseUrl(), pathOrUrl)
}
