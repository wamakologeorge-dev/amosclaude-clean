package com.amosclaudai

import android.content.Intent
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

class MainActivity : AppCompatActivity() {
    private lateinit var greeting: TextView
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar
    private lateinit var adminButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContent())
        loadAccount()
    }

    private fun buildContent(): View {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(24), dp(18), dp(30))
        }

        content.addView(TextView(this).apply {
            text = "Amosclaud"
            textSize = 30f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        })
        greeting = TextView(this).apply { text = "Loading your account…"; textSize = 17f }
        status = TextView(this).apply { text = "Checking Amosclaud core…"; alpha = .7f }
        progress = ProgressBar(this)
        content.addView(greeting)
        content.addView(status)
        content.addView(progress)

        content.addView(tile("Ask Amosclaud", "Native AI chat with safe fallback when an external provider is down") {
            startActivity(Intent(this, AiChatActivity::class.java))
        })
        content.addView(tile("Repositories", "Native Amosclaud repository hosting and workspace access") {
            startActivity(Intent(this, RepositoriesActivity::class.java))
        })
        content.addView(tile("Pipelines", "View and trigger Amosclaud-native CI pipelines") {
            NativeModuleActivity.open(this, "pipelines")
        })
        content.addView(tile("Deployments", "Start and monitor Amosclaud deployments") {
            NativeModuleActivity.open(this, "deployments")
        })
        content.addView(tile("Storage", "Use files stored directly by Amosclaud") {
            NativeModuleActivity.open(this, "storage")
        })
        content.addView(tile("Amos Mail", "Read and send native @amosclaud.com messages") {
            NativeModuleActivity.open(this, "mail")
        })
        content.addView(tile("Community", "Read and create native Amosclaud community posts") {
            NativeModuleActivity.open(this, "community")
        })

        adminButton = Button(this).apply {
            text = "Administrator dashboard"
            visibility = View.GONE
            setOnClickListener { startActivity(Intent(this@MainActivity, AdminActivity::class.java)) }
        }
        content.addView(adminButton)

        content.addView(Button(this).apply {
            text = "Emergency web fallback"
            setOnClickListener { BrowserActivity.open(this@MainActivity, "/") }
        })
        content.addView(Button(this).apply {
            text = "Server settings"
            setOnClickListener { startActivity(Intent(this@MainActivity, SettingsActivity::class.java)) }
        })
        content.addView(Button(this).apply {
            text = "Sign out"
            setOnClickListener { signOut() }
        })

        return ScrollView(this).apply { addView(content) }
    }

    private fun tile(title: String, description: String, action: () -> Unit): View {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        return MaterialCardView(this).apply {
            radius = dp(16).toFloat()
            cardElevation = dp(3).toFloat()
            isClickable = true
            isFocusable = true
            setOnClickListener { action() }
            val body = LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(18), dp(18), dp(18), dp(18))
                addView(TextView(this@MainActivity).apply {
                    text = title
                    textSize = 18f
                    setTypeface(typeface, android.graphics.Typeface.BOLD)
                })
                addView(TextView(this@MainActivity).apply { text = description; alpha = .7f })
            }
            addView(body)
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(14) }
        }
    }

    private fun loadAccount() {
        progress.visibility = View.VISIBLE
        lifecycleScope.launch {
            try {
                val user = AmosclaudApiClient.me(this@MainActivity)
                greeting.text = "Welcome, ${user.name}"
                status.text = "Amosclaud core connected · ${user.email}"
                adminButton.visibility = if (user.isAdmin) View.VISIBLE else View.GONE
            } catch (error: AmosclaudApiClient.ApiException) {
                if (error.statusCode == 401) openAuth() else status.text = error.message
            } catch (_: Exception) {
                status.text = "Amosclaud is temporarily unreachable. Your saved session remains on this device."
            } finally {
                progress.visibility = View.GONE
            }
        }
    }

    private fun signOut() {
        lifecycleScope.launch {
            AmosclaudApiClient.logout(this@MainActivity)
            getSharedPreferences("amosclaud_chat", MODE_PRIVATE).edit().clear().apply()
            openAuth()
        }
    }

    private fun openAuth() {
        startActivity(Intent(this, AuthActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        finish()
    }
}
