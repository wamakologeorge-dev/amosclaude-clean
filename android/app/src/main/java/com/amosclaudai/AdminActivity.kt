package com.amosclaudai

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.amosclaudai.api.AmosclaudApiClient
import com.google.android.material.card.MaterialCardView
import kotlinx.coroutines.launch

class AdminActivity : AppCompatActivity() {
    private lateinit var content: LinearLayout
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContent())
        loadOverview()
    }

    private fun buildContent(): View {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(24), dp(18), dp(24))
        }
        root.addView(TextView(this).apply {
            text = "Administrator"
            textSize = 28f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        })
        status = TextView(this).apply { text = "Loading Amosclaud platform status…"; alpha = .7f }
        progress = ProgressBar(this)
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(status)
        root.addView(progress)
        root.addView(Button(this).apply {
            text = "Refresh"
            setOnClickListener { loadOverview() }
        })
        root.addView(Button(this).apply {
            text = "Open full administrator controls"
            setOnClickListener { BrowserActivity.open(this@AdminActivity, "/admin") }
        })
        root.addView(ScrollView(this).apply { addView(content) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        return root
    }

    private fun loadOverview() {
        progress.visibility = View.VISIBLE
        lifecycleScope.launch {
            try {
                val overview = AmosclaudApiClient.adminOverview(this@AdminActivity)
                content.removeAllViews()
                listOf(
                    "System" to overview.status,
                    "Users" to overview.users.toString(),
                    "Administrators" to overview.administrators.toString(),
                    "Suspended users" to overview.suspendedUsers.toString(),
                    "Repositories" to overview.repositories.toString(),
                    "Pipelines" to overview.pipelines.toString(),
                    "Deployments" to overview.deployments.toString(),
                ).forEach { (label, value) -> content.addView(metric(label, value)) }
                status.text = "Amosclaud core status: ${overview.status}"
            } catch (error: AmosclaudApiClient.ApiException) {
                status.text = if (error.statusCode == 403) "Administrator access is required." else error.message
            } catch (_: Exception) {
                status.text = "Could not load administrator information."
            } finally {
                progress.visibility = View.GONE
            }
        }
    }

    private fun metric(label: String, value: String): View {
        val density = resources.displayMetrics.density
        fun dp(number: Int) = (number * density).toInt()
        return MaterialCardView(this).apply {
            radius = dp(14).toFloat()
            cardElevation = dp(2).toFloat()
            val body = LinearLayout(this@AdminActivity).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(16), dp(14), dp(16), dp(14))
                addView(TextView(this@AdminActivity).apply { text = label; alpha = .65f })
                addView(TextView(this@AdminActivity).apply {
                    text = value
                    textSize = 22f
                    setTypeface(typeface, android.graphics.Typeface.BOLD)
                })
            }
            addView(body)
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                topMargin = dp(12)
            }
        }
    }
}
