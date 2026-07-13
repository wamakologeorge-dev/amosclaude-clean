package com.amosclaudai.api

import android.content.Context
import com.amosclaudai.BuildConfig
import com.amosclaudai.model.ChatResponse
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

object AmosclaudApiClient {
    private const val PREF_NAME = "amosclaudai_prefs"
    private const val KEY_API_URL = "api_url"
    private const val KEY_COOKIES = "session_cookies"
    private val JSON = "application/json; charset=utf-8".toMediaType()
    private val gson = Gson()

    data class User(val id: Int, val name: String, val email: String, val isAdmin: Boolean, val provider: String)
    data class Repository(
        val id: Int,
        val name: String,
        val description: String,
        val visibility: String,
        val defaultBranch: String,
        val updatedAt: String,
    )
    data class AdminOverview(
        val users: Int,
        val administrators: Int,
        val suspendedUsers: Int,
        val repositories: Int,
        val pipelines: Int,
        val deployments: Int,
        val status: String,
    )

    class ApiException(val statusCode: Int, override val message: String) : Exception(message)

    fun getBaseUrl(context: Context): String {
        val prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        return (prefs.getString(KEY_API_URL, BuildConfig.DEFAULT_API_URL) ?: BuildConfig.DEFAULT_API_URL).trimEnd('/')
    }

    fun saveBaseUrl(context: Context, url: String) {
        context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_API_URL, url.trim().trimEnd('/'))
            .apply()
    }

    fun clearSession(context: Context) {
        context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE).edit().remove(KEY_COOKIES).apply()
    }

    private fun client(context: Context): OkHttpClient = OkHttpClient.Builder()
        .cookieJar(PersistentCookieJar(context.applicationContext, getBaseUrl(context).toHttpUrl()))
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(75, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .build()

    private class PersistentCookieJar(context: Context, private val baseUrl: HttpUrl) : CookieJar {
        private val prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        private val cookies = mutableMapOf<String, Cookie>()

        init {
            prefs.getStringSet(KEY_COOKIES, emptySet()).orEmpty().forEach { encoded ->
                Cookie.parse(baseUrl, encoded)?.let { cookies[it.name] = it }
            }
        }

        override fun saveFromResponse(url: HttpUrl, received: List<Cookie>) {
            received.forEach { cookie ->
                if (cookie.expiresAt < System.currentTimeMillis()) cookies.remove(cookie.name)
                else cookies[cookie.name] = cookie
            }
            prefs.edit().putStringSet(KEY_COOKIES, cookies.values.map { it.toString() }.toSet()).apply()
        }

        override fun loadForRequest(url: HttpUrl): List<Cookie> {
            val now = System.currentTimeMillis()
            cookies.entries.removeAll { it.value.expiresAt < now }
            return cookies.values.filter { it.matches(url) }
        }
    }

    private suspend fun request(context: Context, path: String, method: String = "GET", payload: Any? = null): String =
        withContext(Dispatchers.IO) {
            val builder = Request.Builder().url("${getBaseUrl(context)}$path")
            when (method) {
                "POST" -> builder.post(gson.toJson(payload ?: emptyMap<String, Any>()).toRequestBody(JSON))
                "PATCH" -> builder.patch(gson.toJson(payload ?: emptyMap<String, Any>()).toRequestBody(JSON))
                "DELETE" -> {
                    if (payload == null) builder.delete()
                    else builder.delete(gson.toJson(payload).toRequestBody(JSON))
                }
                else -> builder.get()
            }
            client(context).newCall(builder.build()).execute().use { response ->
                val raw = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val detail = runCatching {
                        val map: Map<String, Any?> = gson.fromJson(raw, object : TypeToken<Map<String, Any?>>() {}.type)
                        map["detail"]?.toString()
                    }.getOrNull()
                    throw ApiException(response.code, detail ?: "The Amosclaud server returned HTTP ${response.code}.")
                }
                raw
            }
        }

    private fun userFrom(raw: String): User {
        val map = parseMap(raw)
        return User(
            id = (map["id"] as Number).toInt(),
            name = map["name"]?.toString().orEmpty(),
            email = map["email"]?.toString().orEmpty(),
            isAdmin = map["is_admin"] as? Boolean ?: false,
            provider = map["provider"]?.toString().orEmpty(),
        )
    }

    private fun parseMap(raw: String): Map<String, Any?> =
        gson.fromJson(raw.ifBlank { "{}" }, object : TypeToken<Map<String, Any?>>() {}.type)

    private fun parseList(raw: String): List<Map<String, Any?>> =
        gson.fromJson(raw.ifBlank { "[]" }, object : TypeToken<List<Map<String, Any?>>>() {}.type)

    suspend fun getMap(context: Context, path: String): Map<String, Any?> = parseMap(request(context, path))
    suspend fun getList(context: Context, path: String): List<Map<String, Any?>> = parseList(request(context, path))
    suspend fun postMap(context: Context, path: String, payload: Map<String, Any?>): Map<String, Any?> =
        parseMap(request(context, path, "POST", payload))
    suspend fun delete(context: Context, path: String) { request(context, path, "DELETE") }

    suspend fun login(context: Context, email: String, password: String): User =
        userFrom(request(context, "/api/v1/auth/login", "POST", mapOf("email" to email, "password" to password)))

    suspend fun requestRegistrationCode(context: Context, name: String, email: String, password: String) {
        request(context, "/api/v1/auth/register/request-code", "POST", mapOf("name" to name, "email" to email, "password" to password))
    }

    suspend fun verifyRegistration(context: Context, email: String, password: String, code: String): User =
        userFrom(request(context, "/api/v1/auth/register/verify", "POST", mapOf("email" to email, "password" to password, "code" to code)))

    suspend fun me(context: Context): User = userFrom(request(context, "/api/v1/auth/me"))

    suspend fun logout(context: Context) {
        runCatching { request(context, "/api/v1/auth/logout", "POST") }
        clearSession(context)
    }

    suspend fun deleteAccount(context: Context, email: String, password: String?) {
        request(
            context,
            "/api/v1/account",
            "DELETE",
            buildMap<String, Any?> {
                put("confirmation", email)
                if (!password.isNullOrBlank()) put("password", password)
            },
        )
        clearSession(context)
    }

    suspend fun sendMessage(context: Context, message: String, sessionId: String?): ChatResponse {
        val map = parseMap(request(context, "/api/chat", "POST", buildMap<String, Any?> {
            put("message", message)
            put("start_pr_task", false)
            put("base_branch", "main")
            if (!sessionId.isNullOrBlank()) put("session_id", sessionId)
        }))
        return ChatResponse(
            reply = map["reply"]?.toString().orEmpty().ifBlank { "Amosclaud returned an empty response." },
            sessionId = map["session_id"]?.toString().orEmpty(),
            timestamp = map["timestamp"]?.toString().orEmpty(),
        )
    }

    suspend fun repositories(context: Context): List<Repository> = getList(context, "/api/v1/repositories").map { row ->
        Repository(
            id = (row["id"] as Number).toInt(),
            name = row["name"]?.toString().orEmpty(),
            description = row["description"]?.toString().orEmpty(),
            visibility = row["visibility"]?.toString().orEmpty(),
            defaultBranch = row["default_branch"]?.toString().orEmpty(),
            updatedAt = row["updated_at"]?.toString().orEmpty(),
        )
    }

    suspend fun adminOverview(context: Context): AdminOverview {
        val row = getMap(context, "/api/v1/admin/overview")
        fun int(name: String) = (row[name] as? Number)?.toInt() ?: 0
        return AdminOverview(
            users = int("users"),
            administrators = int("administrators"),
            suspendedUsers = int("suspended_users"),
            repositories = int("repositories"),
            pipelines = int("pipelines"),
            deployments = int("deployments"),
            status = row["status"]?.toString().orEmpty(),
        )
    }

    suspend fun testConnection(context: Context): Boolean = runCatching { request(context, "/health") }.isSuccess
}
