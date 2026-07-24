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

class RepositoriesActivity : AppCompatActivity() {
    private lateinit var list: LinearLayout
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContent())
        loadRepositories()
    }

    private fun buildContent(): View {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(18), dp(18), dp(18))
        }
        root.addView(TextView(this).apply {
            text = "Repositories"
            textSize = 28f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        })
        status = TextView(this).apply { text = "Loading repositories…"; alpha = .7f }
        root.addView(status)
        progress = ProgressBar(this)
        root.addView(progress)
        root.addView(Button(this).apply {
            text = "Refresh"
            setOnClickListener { loadRepositories() }
        })
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(ScrollView(this).apply { addView(list) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        return root
    }

    private fun loadRepositories() {
        progress.visibility = View.VISIBLE
        status.text = "Loading repositories…"
        lifecycleScope.launch {
            try {
                val repositories = AmosclaudApiClient.repositories(this@RepositoriesActivity)
                list.removeAllViews()
                repositories.forEach { repository ->
                    val card = MaterialCardView(this@RepositoriesActivity).apply {
                        radius = 18f
                        cardElevation = 3f
                        val body = LinearLayout(this@RepositoriesActivity).apply {
                            orientation = LinearLayout.VERTICAL
                            setPadding(28, 24, 28, 24)
                            addView(TextView(this@RepositoriesActivity).apply {
                                text = repository.name
                                textSize = 18f
                                setTypeface(typeface, android.graphics.Typeface.BOLD)
                            })
                            addView(TextView(this@RepositoriesActivity).apply {
                                text = repository.description.ifBlank { "No description" }
                            })
                            addView(TextView(this@RepositoriesActivity).apply {
                                text = "${repository.visibility} · ${repository.defaultBranch}"
                                alpha = .65f
                            })
                            addView(Button(this@RepositoriesActivity).apply {
                                text = "Open workspace"
                                setOnClickListener {
                                    BrowserActivity.open(this@RepositoriesActivity, "/workspace/${repository.id}")
                                }
                            })
                        }
                        addView(body)
                    }
                    val params = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                    params.topMargin = 18
                    list.addView(card, params)
                }
                status.text = "${repositories.size} repositories"
            } catch (error: AmosclaudApiClient.ApiException) {
                status.text = error.message
            } catch (_: Exception) {
                status.text = "Could not load repositories."
            } finally {
                progress.visibility = View.GONE
            }
        }
    }
}
