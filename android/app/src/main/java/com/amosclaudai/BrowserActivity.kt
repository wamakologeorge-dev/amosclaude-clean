package com.amosclaudai

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.KeyEvent
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import com.amosclaudai.databinding.ActivityBrowserBinding

/**
 * Full-featured WebView-based browser activity.
 * Supports address bar navigation, back/forward, bookmarks, and page loading progress.
 */
class BrowserActivity : AppCompatActivity() {

    private lateinit var binding: ActivityBrowserBinding

    private val bookmarks = listOf(
        "Amosclaud"   to HOME_URL,
        "GitHub"      to "https://github.com",
        "Android Docs" to "https://developer.android.com",
        "Python Docs" to "https://docs.python.org/3/",
        "Docker Hub"  to "https://hub.docker.com",
    )

    companion object {
        const val HOME_URL = "https://web-production-d94ca.up.railway.app/"
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityBrowserBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.apply {
            title = getString(R.string.title_browser)
            setDisplayHomeAsUpEnabled(true)
        }

        setupWebView()
        setupControls()
        setupBookmarks()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (binding.webView.canGoBack()) {
                    binding.webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        val startUrl = intent.getStringExtra("url") ?: HOME_URL
        binding.webView.loadUrl(startUrl)
        binding.etUrl.setText(startUrl)
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        binding.webView.apply {
            settings.apply {
                javaScriptEnabled        = true
                domStorageEnabled        = true
                loadWithOverviewMode     = true
                useWideViewPort          = true
                builtInZoomControls      = true
                displayZoomControls      = false
                setSupportMultipleWindows(false)
                allowFileAccess          = false
                allowContentAccess       = false
            }

            webChromeClient = object : WebChromeClient() {
                override fun onProgressChanged(view: WebView, newProgress: Int) {
                    binding.progressBar.progress = newProgress
                    binding.progressBar.visibility =
                        if (newProgress < 100) android.view.View.VISIBLE else android.view.View.GONE
                }

                override fun onReceivedTitle(view: WebView, title: String?) {
                    supportActionBar?.subtitle = title
                }
            }

            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val scheme = request.url.scheme?.lowercase()
                    if (scheme != "http" && scheme != "https") return true
                    binding.etUrl.setText(request.url.toString())
                    return false
                }

                override fun onPageFinished(view: WebView, url: String?) {
                    binding.etUrl.setText(url)
                    updateNavButtons()
                }
            }
        }
    }

    private fun setupControls() {
        binding.etUrl.setOnEditorActionListener { _, actionId, event ->
            if (actionId == EditorInfo.IME_ACTION_GO ||
                (event?.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN)) {
                navigateTo(binding.etUrl.text.toString())
                true
            } else false
        }

        binding.btnGo.setOnClickListener { navigateTo(binding.etUrl.text.toString()) }
        binding.btnBack.setOnClickListener { if (binding.webView.canGoBack()) binding.webView.goBack() }
        binding.btnForward.setOnClickListener { if (binding.webView.canGoForward()) binding.webView.goForward() }
        binding.btnRefresh.setOnClickListener { binding.webView.reload() }
        binding.btnHome.setOnClickListener { navigateTo(HOME_URL) }
    }

    private fun setupBookmarks() {
        bookmarks.forEach { (label, url) ->
            val chip = com.google.android.material.chip.Chip(this).apply {
                text = label
                isCheckable = false
                setOnClickListener { navigateTo(url) }
            }
            binding.chipGroupBookmarks.addView(chip)
        }
    }

    private fun navigateTo(input: String) {
        hideKeyboard()
        val url = when {
            input.startsWith("http://") || input.startsWith("https://") -> input
            input.contains(".") -> "https://$input"
            else -> "https://www.google.com/search?q=${android.net.Uri.encode(input)}"
        }
        binding.etUrl.setText(url)
        binding.webView.loadUrl(url)
    }

    private fun updateNavButtons() {
        binding.btnBack.isEnabled    = binding.webView.canGoBack()
        binding.btnForward.isEnabled = binding.webView.canGoForward()
    }

    private fun hideKeyboard() {
        val imm = getSystemService(InputMethodManager::class.java)
        imm.hideSoftInputFromWindow(binding.etUrl.windowToken, 0)
    }

    override fun onPause() {
        super.onPause()
        binding.webView.onPause()
    }

    override fun onResume() {
        super.onResume()
        binding.webView.onResume()
    }

    override fun onDestroy() {
        binding.webView.destroy()
        super.onDestroy()
    }
}
