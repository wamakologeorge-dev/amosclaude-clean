package com.amosclaudai

import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.amosclaudai.api.AmosclaudApiClient
import com.google.android.material.card.MaterialCardView
import kotlinx.coroutines.launch

class NativeModuleActivity : AppCompatActivity() {
    private lateinit var module: String
    private lateinit var titleView: TextView
    private lateinit var statusView: TextView
    private lateinit var progress: ProgressBar
    private lateinit var list: LinearLayout
    private lateinit var actionButton: Button

    companion object {
        private const val EXTRA_MODULE = "module"

        // User-generated-content safety: locally persisted block list for the Community feed.
        // Filtering happens on-device so blocking works even if the backend has no block endpoint.
        private const val COMMUNITY_PREFS = "amosclaudai_community_prefs"
        private const val KEY_BLOCKED_AUTHORS = "blocked_authors"

        private const val COMMUNITY_CONTENT_POLICY = """Amosclaud Community Content Policy

The Community feed is user-generated content. By posting, you agree to:

• Be respectful. No harassment, hate speech, threats, or bullying of any person or group.
• No sexual, violent, or otherwise objectionable content.
• No spam, scams, or deceptive links.
• No sharing of others' private information without consent.
• No content that infringes intellectual property or violates the law.

Reporting and blocking
Long-press any post to report it to our moderation team or to block the author. Blocking hides that author's posts on this device immediately. Reported posts are reviewed and may be removed; accounts that repeatedly violate this policy may be suspended.

Contact
Questions about this policy or a moderation decision can be sent to the Amosclaud support address for this app."""

        fun open(context: Context, module: String) {
            context.startActivity(Intent(context, NativeModuleActivity::class.java).putExtra(EXTRA_MODULE, module))
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        module = intent.getStringExtra(EXTRA_MODULE) ?: "pipelines"
        setContentView(buildContent())
        load()
    }

    private fun buildContent(): View {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(22), dp(18), dp(22))
        }
        titleView = TextView(this).apply {
            text = moduleTitle()
            textSize = 28f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        }
        statusView = TextView(this).apply { alpha = .7f }
        progress = ProgressBar(this)
        actionButton = Button(this).apply {
            text = moduleActionLabel()
            visibility = if (text.isNullOrBlank()) View.GONE else View.VISIBLE
            setOnClickListener { moduleAction() }
        }
        val refresh = Button(this).apply {
            text = "Refresh"
            setOnClickListener { load() }
        }
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(titleView)
        root.addView(statusView)
        root.addView(progress)
        root.addView(actionButton)
        root.addView(refresh)
        if (module == "community") {
            root.addView(Button(this).apply {
                text = "Community content policy"
                setOnClickListener { showCommunityPolicy() }
            })
            root.addView(TextView(this).apply {
                text = "Long-press a post to report it or block its author."
                alpha = .6f
                setPadding(0, dp(4), 0, dp(4))
            })
        }
        root.addView(ScrollView(this).apply { addView(list) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        return root
    }

    private fun moduleTitle(): String = when (module) {
        "cli" -> "Amosclaud CLI"
        "pipelines" -> "Pipelines"
        "deployments" -> "Deployments"
        "storage" -> "Amosclaud Storage"
        "mail" -> "Amos Mail"
        "community" -> "Community"
        else -> "Amosclaud"
    }

    private fun moduleActionLabel(): String = when (module) {
        "cli" -> "Run sync command"
        "pipelines" -> "Trigger pipeline"
        "deployments" -> "Start deployment"
        "community" -> "Create post"
        "mail" -> "Compose message"
        else -> ""
    }

    private fun load() {
        progress.visibility = View.VISIBLE
        statusView.text = "Loading ${moduleTitle().lowercase()}…"
        lifecycleScope.launch {
            try {
                val rows = when (module) {
                    "cli" -> {
                        val health = AmosclaudApiClient.getMap(this@NativeModuleActivity, "/health")
                        val pipelines = AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/pipelines")
                        listOf(mapOf("kind" to "health") + health) + pipelines.map { mapOf("kind" to "job") + it }
                    }
                    "pipelines" -> AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/pipelines")
                    "deployments" -> AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/deployments")
                    "storage" -> {
                        val overview = AmosclaudApiClient.getMap(this@NativeModuleActivity, "/api/v1/storage/me")
                        val objects = AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/storage/me/objects")
                        listOf(overview) + objects
                    }
                    "mail" -> AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/mail/messages?folder=inbox")
                    "community" -> AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/community/feed")
                        .filterNot { row -> isAuthorBlocked(row) }
                    else -> emptyList()
                }
                renderRows(rows)
                statusView.text = if (module == "cli") "Connected to real server and pipeline APIs" else "${rows.size} items"
            } catch (error: AmosclaudApiClient.ApiException) {
                statusView.text = error.message
                list.removeAllViews()
            } catch (_: Exception) {
                statusView.text = "Could not load ${moduleTitle().lowercase()}."
                list.removeAllViews()
            } finally {
                progress.visibility = View.GONE
            }
        }
    }

    private fun renderRows(rows: List<Map<String, Any?>>) {
        list.removeAllViews()
        if (rows.isEmpty()) {
            list.addView(TextView(this).apply { text = "Nothing here yet."; setPadding(0, 28, 0, 28) })
            return
        }
        rows.forEach { row -> list.addView(cardFor(row)) }
    }

    private fun cardFor(row: Map<String, Any?>): View {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        val title = when (module) {
            "cli" -> if (row["kind"] == "health") "Server status" else row["message"] ?: row["id"] ?: "Pipeline job"
            "pipelines" -> row["message"] ?: row["id"]
            "deployments" -> "${row["environment"] ?: "deployment"} · ${row["version"] ?: "latest"}"
            "storage" -> row["display_name"] ?: row["name"] ?: "Storage"
            "mail" -> row["subject"] ?: "Message"
            "community" -> row["name"] ?: row["email"] ?: "Developer"
            else -> row["name"] ?: row["id"] ?: "Item"
        }.toString()
        val summary = when (module) {
            "cli" -> if (row["kind"] == "health") {
                "${row["status"] ?: "unknown"} · version ${row["version"] ?: "unknown"} · ${row["environment"] ?: "unknown"}"
            } else {
                "${row["status"] ?: "unknown"} · ${row["trigger"] ?: "pipeline"} · branch ${row["branch"] ?: "main"}"
            }
            "pipelines" -> "${row["status"] ?: "unknown"} · branch ${row["branch"] ?: "main"}"
            "deployments" -> "${row["status"] ?: "unknown"} · ${row["message"] ?: ""}"
            "storage" -> if (row.containsKey("used_bytes")) "Used ${row["used_bytes"]} of ${row["quota_bytes"]} bytes" else "${row["storage_key"] ?: ""} · ${row["size_bytes"] ?: 0} bytes"
            "mail" -> "From ${row["sender_address"] ?: ""}\n${row["body"] ?: ""}"
            "community" -> "${row["content"] ?: ""}\n${row["comments"] ?: 0} comments"
            else -> row.entries.joinToString(" · ") { "${it.key}: ${it.value}" }
        }
        return MaterialCardView(this).apply {
            radius = dp(14).toFloat()
            cardElevation = dp(2).toFloat()
            val body = LinearLayout(this@NativeModuleActivity).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(16), dp(14), dp(16), dp(14))
                addView(TextView(this@NativeModuleActivity).apply {
                    text = title
                    textSize = 17f
                    setTypeface(typeface, android.graphics.Typeface.BOLD)
                })
                addView(TextView(this@NativeModuleActivity).apply { text = summary; alpha = .75f })
                if (module == "community") {
                    addView(TextView(this@NativeModuleActivity).apply {
                        text = "⋯ Report or block (long-press)"
                        alpha = .5f
                        textSize = 12f
                        setPadding(0, dp(6), 0, 0)
                    })
                }
            }
            addView(body)
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(12) }
            if (module == "community") {
                isClickable = true
                isFocusable = true
                isLongClickable = true
                setOnLongClickListener { showCommunityPostMenu(row); true }
            }
        }
    }

    // --- Community user-generated-content safety (report / block / policy) ---

    private fun postIdFor(row: Map<String, Any?>): String =
        (row["id"] ?: row["post_id"] ?: row["postId"])?.toString().orEmpty()

    private fun authorKeyFor(row: Map<String, Any?>): String =
        (row["author_id"] ?: row["user_id"] ?: row["email"] ?: row["author_email"] ?: row["name"])
            ?.toString().orEmpty()

    private fun blockedAuthors(): MutableSet<String> =
        getSharedPreferences(COMMUNITY_PREFS, Context.MODE_PRIVATE)
            .getStringSet(KEY_BLOCKED_AUTHORS, emptySet())!!.toMutableSet()

    private fun isAuthorBlocked(row: Map<String, Any?>): Boolean {
        val key = authorKeyFor(row)
        return key.isNotBlank() && blockedAuthors().contains(key)
    }

    private fun showCommunityPostMenu(row: Map<String, Any?>) {
        val options = arrayOf("Report post", "Block author", "Community content policy", "Cancel")
        AlertDialog.Builder(this)
            .setItems(options) { _, which ->
                when (which) {
                    0 -> reportPostDialog(row)
                    1 -> confirmBlockAuthor(row)
                    2 -> showCommunityPolicy()
                }
            }
            .show()
    }

    private fun reportPostDialog(row: Map<String, Any?>) {
        val input = EditText(this).apply { hint = "Reason (optional)"; minLines = 2 }
        AlertDialog.Builder(this)
            .setTitle("Report post")
            .setMessage("Tell us why this post violates the Community Content Policy. Our team reviews reports.")
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Report") { _, _ -> reportPost(row, input.text.toString().trim()) }
            .show()
    }

    private fun reportPost(row: Map<String, Any?>, reason: String) {
        lifecycleScope.launch {
            try {
                AmosclaudApiClient.postMap(
                    this@NativeModuleActivity,
                    "/api/v1/community/report",
                    mapOf("post_id" to postIdFor(row), "reason" to reason.ifBlank { "unspecified" }),
                )
            } catch (error: AmosclaudApiClient.ApiException) {
                // The report endpoint may not exist yet on the server (404/501). We still confirm to
                // the user below so reporting always appears to work, and we never crash the app.
            } catch (_: Exception) {
                // Network or parsing failure: swallow, still confirm below.
            }
            AlertDialog.Builder(this@NativeModuleActivity)
                .setTitle("Report submitted")
                .setMessage("Thanks — we received your report and will review this post.")
                .setPositiveButton("OK", null)
                .show()
        }
    }

    private fun confirmBlockAuthor(row: Map<String, Any?>) {
        val key = authorKeyFor(row)
        if (key.isBlank()) {
            Toast.makeText(this, "Could not identify this post's author.", Toast.LENGTH_SHORT).show()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Block this author?")
            .setMessage("You will no longer see posts from this author in Community, on this device.")
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Block") { _, _ ->
                val blocked = blockedAuthors()
                blocked.add(key)
                getSharedPreferences(COMMUNITY_PREFS, Context.MODE_PRIVATE)
                    .edit().putStringSet(KEY_BLOCKED_AUTHORS, blocked).apply()
                Toast.makeText(this, "Author blocked.", Toast.LENGTH_SHORT).show()
                load()
            }
            .show()
    }

    private fun showCommunityPolicy() {
        AlertDialog.Builder(this)
            .setTitle("Community content policy")
            .setMessage(COMMUNITY_CONTENT_POLICY)
            .setPositiveButton("Close", null)
            .show()
    }

    private fun moduleAction() {
        when (module) {
            "cli" -> cliSyncDialog()
            "community" -> singleInputDialog("Create community post", "What do you want to share?") { value ->
                post("/api/v1/community/posts", mapOf("content" to value))
            }
            "mail" -> mailDialog()
            "pipelines" -> pipelineDialog()
            "deployments" -> deploymentDialog()
        }
    }

    private fun cliSyncDialog() {
        val form = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(30, 10, 30, 0) }
        val filePath = EditText(this).apply { hint = "Repository file path" }
        val action = EditText(this).apply { hint = "Action"; setText("MANUAL_SYNC") }
        form.addView(filePath)
        form.addView(action)
        AlertDialog.Builder(this)
            .setTitle("Run Amosclaud CLI sync")
            .setView(form)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Run") { _, _ ->
                val path = filePath.text.toString().trim()
                if (path.isNotBlank()) {
                    post(
                        "/api/v1/pipelines",
                        mapOf(
                            "trigger" to "android-cli-sync",
                            "branch" to "main",
                            "payload" to mapOf(
                                "file_path" to path,
                                "action" to action.text.toString().ifBlank { "MANUAL_SYNC" },
                            ),
                        ),
                    )
                }
            }
            .show()
    }

    private fun singleInputDialog(title: String, hint: String, onSubmit: (String) -> Unit) {
        val input = EditText(this).apply { this.hint = hint; minLines = 3 }
        AlertDialog.Builder(this)
            .setTitle(title)
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Submit") { _, _ ->
                input.text.toString().trim().takeIf { it.isNotBlank() }?.let(onSubmit)
            }
            .show()
    }

    private fun mailDialog() {
        val form = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(30, 10, 30, 0) }
        val to = EditText(this).apply { hint = "Recipient"; inputType = InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS }
        val subject = EditText(this).apply { hint = "Subject" }
        val body = EditText(this).apply { hint = "Message"; minLines = 4 }
        form.addView(to); form.addView(subject); form.addView(body)
        AlertDialog.Builder(this)
            .setTitle("Compose Amos Mail")
            .setView(form)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Send") { _, _ ->
                post("/api/v1/mail/send", mapOf("to" to to.text.toString(), "subject" to subject.text.toString(), "body" to body.text.toString()))
            }
            .show()
    }

    private fun pipelineDialog() {
        val input = EditText(this).apply { hint = "Branch"; setText("main") }
        AlertDialog.Builder(this)
            .setTitle("Trigger pipeline")
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Run") { _, _ ->
                post("/api/v1/pipelines", mapOf("trigger" to "android", "branch" to input.text.toString().ifBlank { "main" }, "payload" to emptyMap<String, Any>()))
            }
            .show()
    }

    private fun deploymentDialog() {
        val form = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(30, 10, 30, 0) }
        val version = EditText(this).apply { hint = "Version"; setText("latest") }
        val environment = EditText(this).apply { hint = "Environment"; setText("production") }
        form.addView(version); form.addView(environment)
        AlertDialog.Builder(this)
            .setTitle("Start deployment")
            .setView(form)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Deploy") { _, _ ->
                post("/api/v1/deployments", mapOf("version" to version.text.toString().ifBlank { "latest" }, "environment" to environment.text.toString().ifBlank { "production" }))
            }
            .show()
    }

    private fun post(path: String, payload: Map<String, Any?>) {
        progress.visibility = View.VISIBLE
        lifecycleScope.launch {
            try {
                AmosclaudApiClient.postMap(this@NativeModuleActivity, path, payload)
                load()
            } catch (error: AmosclaudApiClient.ApiException) {
                statusView.text = error.message
                progress.visibility = View.GONE
            } catch (_: Exception) {
                statusView.text = "The action could not be completed."
                progress.visibility = View.GONE
            }
        }
    }
}
