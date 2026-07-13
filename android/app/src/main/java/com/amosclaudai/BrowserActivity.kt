package com.amosclaudai

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.KeyEvent
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import com.amosclaudai.api.AmosclaudApiClient
import com.amosclaudai.databinding.ActivityBrowserBinding

class BrowserActivity : AppCompatActivity() {
    private lateinit var binding: ActivityBrowserBinding

    companion object {
        private const val EXTRA_PATH = "path"

        fun open(context: Context, path: String = "/") {
            context.startActivity(Intent(context, BrowserActivity::class.java).putExtra(EXTRA_PATH, path))
        }
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
                if (binding.webView.canGoBack()) binding.webView.goBack()
                else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })

        val baseUrl = AmosclaudApiClient.getBaseUrl(this)
        val path = intent.getStringExtra(EXTRA_PATH) ?: "/"
        val startUrl = if (path.startsWith("http://") || path.startsWith("https://")) path else "$baseUrl/${path.trimStart('/')}"
        binding.webView.loadUrl(startUrl)
        binding.etUrl.setText(startUrl)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(binding.webView, false)
        binding.webView.apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                loadWithOverviewMode = true
                useWideViewPort = true
                builtInZoomControls = true
                displayZoomControls = false
                setSupportMultipleWindows(false)
                allowFileAccess = false
                allowContentAccess = false
            }
            webChromeClient = object : WebChromeClient() {
                override fun onProgressChanged(view: WebView, newProgress: Int) {
                    binding.progressBar.progress = newProgress
                    binding.progressBar.visibility = if (newProgress < 100) android.view.View.VISIBLE else android.view.View.GONE
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
            if (actionId == EditorInfo.IME_ACTION_GO || (event?.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN)) {
                navigateTo(binding.etUrl.text.toString())
                true
            } else false
        }
        binding.btnGo.setOnClickListener { navigateTo(binding.etUrl.text.toString()) }
        binding.btnBack.setOnClickListener { if (binding.webView.canGoBack()) binding.webView.goBack() }
        binding.btnForward.setOnClickListener { if (binding.webView.canGoForward()) binding.webView.goForward() }
        binding.btnRefresh.setOnClickListener { binding.webView.reload() }
        binding.btnHome.setOnClickListener { navigateTo(AmosclaudApiClient.getBaseUrl(this)) }
    }

    private fun setupBookmarks() {
        listOf(
            "Amosclaud" to AmosclaudApiClient.getBaseUrl(this),
            "Repositories" to "${AmosclaudApiClient.getBaseUrl(this)}/repositories",
            "Admin" to "${AmosclaudApiClient.getBaseUrl(this)}/admin",
        ).forEach { (label, url) ->
            binding.chipGroupBookmarks.addView(com.google.android.material.chip.Chip(this).apply {
                text = label
                isCheckable = false
                setOnClickListener { navigateTo(url) }
            })
        }
    }

    private fun navigateTo(input: String) {
        hideKeyboard()
        val url = when {
            input.startsWith("http://") || input.startsWith("https://") -> input
            input.startsWith("/") -> "${AmosclaudApiClient.getBaseUrl(this)}$input"
            input.contains(".") -> "https://$input"
            else -> "${AmosclaudApiClient.getBaseUrl(this)}/${input.trimStart('/')}"
        }
        binding.etUrl.setText(url)
        binding.webView.loadUrl(url)
    }

    private fun updateNavButtons() {
        binding.btnBack.isEnabled = binding.webView.canGoBack()
        binding.btnForward.isEnabled = binding.webView.canGoForward()
    }

    private fun hideKeyboard() {
        getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(binding.etUrl.windowToken, 0)
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
