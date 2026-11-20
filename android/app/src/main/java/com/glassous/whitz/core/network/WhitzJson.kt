package com.glassous.whitz.core.network

import kotlinx.serialization.json.Json

val WhitzJson = Json {
    ignoreUnknownKeys = true
    isLenient = true
    encodeDefaults = true
    explicitNulls = false
}
