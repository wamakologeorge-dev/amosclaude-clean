package com.amosclaudai.api

import android.content.Context
import com.amosclaudai.BuildConfig
import com.amosclaudai.model.ChatResponse
import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * Handles all HTTP communication with the Amosclaud-AI backend.
 */
object AmosclaudApiClient {

    private const val PREF_NAME     = "amosclaudai_prefs"
    private const val KEY_API_URL   = "api_url"
    private val JSON = "application/json; charset=utf-8".toMediaType()
    private val gson = Gson()

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .build()

    // ── URL helpers ──────────────────────────────────────────────────────────

    fun getBaseUrl(context: Context): String {
        val prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_API_URL, BuildConfig.DEFAULT_API_URL)
            ?: BuildConfig.DEFAULT_API_URL
    }

    fun saveBaseUrl(context: Context, url: String) {
        context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_API_URL, url)
            .apply()
    }

    // ── API calls ────────────────────────────────────────────────────────────

    /**
     * POST /api/chat
     * Suspending — must be called from a coroutine.
     */
    suspend fun sendMessage(
        baseUrl: String,
        message: String,
        sessionId: String?,
    ): ChatResponse = withContext(Dispatchers.IO) {
        val payload = buildMap<String, Any?> {
            put("message", message)
            if (sessionId != null) put("session_id", sessionId)
        }
        val body = gson.toJson(payload).toRequestBody(JSON)
        val request = Request.Builder()
            .url("$baseUrl/api/chat")
            .post(body)
            .build()

        val responseBody = http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Server error: ${response.code}")
            response.body?.string() ?: error("Empty response body")
        }

        val raw = gson.fromJson(responseBody, Map::class.java)
        ChatResponse(
            reply     = raw["reply"] as? String ?: "",
            sessionId = raw["session_id"] as? String ?: "",
            timestamp = raw["timestamp"] as? String ?: "",
        )
    }

    /**
     * GET /health
     * Returns true if the server responds with status "ok".
     */
    suspend fun testConnection(baseUrl: String): Boolean = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/health")
            .get()
            .build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return@withContext false
            val body = response.body?.string() ?: return@withContext false
            val map = runCatching { gson.fromJson(body, Map::class.java) }.getOrNull()
            map?.get("status") == "ok"
        }
    }
}
