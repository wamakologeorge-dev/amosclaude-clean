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
        root.addView(ScrollView(this).apply { addView(list) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        return root
    }

    private fun moduleTitle(): String = when (module) {
        "pipelines" -> "Pipelines"
        "deployments" -> "Deployments"
        "storage" -> "Amosclaud Storage"
        "mail" -> "Amos Mail"
        "community" -> "Community"
        else -> "Amosclaud"
    }

    private fun moduleActionLabel(): String = when (module) {
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
                    "pipelines" -> AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/pipelines")
                    "deployments" -> AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/deployments")
                    "storage" -> {
                        val overview = AmosclaudApiClient.getMap(this@NativeModuleActivity, "/api/v1/storage/me")
                        val objects = AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/storage/me/objects")
                        listOf(overview) + objects
                    }
                    "mail" -> AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/mail/messages?folder=inbox")
                    "community" -> AmosclaudApiClient.getList(this@NativeModuleActivity, "/api/v1/community/feed")
                    else -> emptyList()
                }
                renderRows(rows)
                statusView.text = "${rows.size} items"
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
            "pipelines" -> row["message"] ?: row["id"]
            "deployments" -> "${row["environment"] ?: "deployment"} · ${row["version"] ?: "latest"}"
            "storage" -> row["display_name"] ?: row["name"] ?: "Storage"
            "mail" -> row["subject"] ?: "Message"
            "community" -> row["name"] ?: row["email"] ?: "Developer"
            else -> row["name"] ?: row["id"] ?: "Item"
        }.toString()
        val summary = when (module) {
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
            }
            addView(body)
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(12) }
        }
    }

    private fun moduleAction() {
        when (module) {
            "community" -> singleInputDialog("Create community post", "What do you want to share?") { value ->
                post("/api/v1/community/posts", mapOf("content" to value))
            }
            "mail" -> mailDialog()
            "pipelines" -> pipelineDialog()
            "deployments" -> deploymentDialog()
        }
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
