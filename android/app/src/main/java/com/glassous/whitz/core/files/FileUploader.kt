package com.glassous.whitz.core.files

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import com.glassous.whitz.core.network.ApiException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okio.BufferedSink
import java.io.IOException

data class LocalPickedFile(
    val uri: Uri,
    val filename: String,
    val mimeType: String,
    val sizeBytes: Long,
)

object UriFileReader {
    fun inspect(contentResolver: ContentResolver, uri: Uri): LocalPickedFile? {
        var name = "file"
        var size = -1L
        contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val nameIdx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            val sizeIdx = cursor.getColumnIndex(OpenableColumns.SIZE)
            if (cursor.moveToFirst()) {
                if (nameIdx >= 0) name = cursor.getString(nameIdx) ?: name
                if (sizeIdx >= 0) size = cursor.getLong(sizeIdx)
            }
        }
        if (size <= 0L) {
            size = try {
                contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
            } catch (_: Exception) {
                -1L
            }
        }
        val mime = contentResolver.getType(uri)
            ?: FileValidator.getFileSpec(name)?.mime
            ?: "application/octet-stream"
        return LocalPickedFile(
            uri = uri,
            filename = name,
            mimeType = mime,
            sizeBytes = size.coerceAtLeast(0L),
        )
    }
}

class CosUploader(
    private val client: OkHttpClient,
    private val contentResolver: ContentResolver,
) {
    suspend fun putFile(
        uploadUrl: String,
        headers: Map<String, String>,
        file: LocalPickedFile,
        onProgress: (Int) -> Unit,
    ): String? = withContext(Dispatchers.IO) {
        val contentType = (headers["Content-Type"] ?: file.mimeType).toMediaTypeOrNull()
        val body = object : RequestBody() {
            override fun contentType() = contentType
            override fun contentLength() = if (file.sizeBytes > 0) file.sizeBytes else -1L
            override fun writeTo(sink: BufferedSink) {
                val input = contentResolver.openInputStream(file.uri)
                    ?: throw IOException("无法读取所选文件")
                input.use { stream ->
                    val buffer = ByteArray(16 * 1024)
                    var uploaded = 0L
                    val total = file.sizeBytes
                    while (true) {
                        val read = stream.read(buffer)
                        if (read == -1) break
                        sink.write(buffer, 0, read)
                        uploaded += read
                        if (total > 0) {
                            val pct = ((uploaded * 100) / total).toInt().coerceIn(1, 99)
                            onProgress(pct)
                        }
                    }
                }
            }
        }

        val builder = Request.Builder().url(uploadUrl).put(body)
        headers.forEach { (k, v) ->
            if (!k.equals("Content-Length", ignoreCase = true)) {
                builder.header(k, v)
            }
        }
        client.newCall(builder.build()).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw ApiException(resp.code, "直传 COS 失败 (HTTP ${resp.code})")
            }
            onProgress(100)
            resp.header("ETag")?.replace("\"", "")
        }
    }
}
