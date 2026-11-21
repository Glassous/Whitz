package com.glassous.whitz.core.files

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

object AvatarEncoder {
    suspend fun encodeToDataUrl(contentResolver: ContentResolver, uri: Uri, maxDim: Int = 512): String =
        withContext(Dispatchers.IO) {
            val stream = contentResolver.openInputStream(uri)
                ?: throw IllegalStateException("无法读取图片")
            val orig = stream.use { BitmapFactory.decodeStream(it) }
                ?: throw IllegalStateException("无效的图片格式")
            val scale = minOf(maxDim.toFloat() / orig.width, maxDim.toFloat() / orig.height, 1f)
            val w = (orig.width * scale).toInt().coerceAtLeast(1)
            val h = (orig.height * scale).toInt().coerceAtLeast(1)
            val scaled = if (w != orig.width || h != orig.height) {
                Bitmap.createScaledBitmap(orig, w, h, true)
            } else orig
            val out = ByteArrayOutputStream()
            scaled.compress(Bitmap.CompressFormat.JPEG, 88, out)
            "data:image/jpeg;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
        }
}
