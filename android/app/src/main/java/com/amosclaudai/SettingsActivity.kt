package com.amosclaudai

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.amosclaudai.api.AmosclaudApiClient
import com.amosclaudai.databinding.ActivitySettingsBinding
import kotlinx.coroutines.launch

/**
 * Settings screen — allows configuring the backend API URL.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.apply {
            title = getString(R.string.title_settings)
            setDisplayHomeAsUpEnabled(true)
        }

        // Load saved URL
        binding.etApiUrl.setText(AmosclaudApiClient.getBaseUrl(this))

        binding.btnSave.setOnClickListener {
            val url = binding.etApiUrl.text.toString().trim().trimEnd('/')
            if (url.isEmpty()) {
                binding.etApiUrl.error = getString(R.string.error_url_required)
                return@setOnClickListener
            }
            AmosclaudApiClient.saveBaseUrl(this, url)
            Toast.makeText(this, R.string.settings_saved, Toast.LENGTH_SHORT).show()
        }

        binding.btnTestConnection.setOnClickListener {
            val url = binding.etApiUrl.text.toString().trim().trimEnd('/')
            binding.tvConnectionStatus.text = getString(R.string.status_testing)
            lifecycleScope.launch {
                try {
                    val ok = AmosclaudApiClient.testConnection(url)
                    binding.tvConnectionStatus.text = if (ok)
                        getString(R.string.status_connected)
                    else
                        getString(R.string.status_failed)
                } catch (e: Exception) {
                    binding.tvConnectionStatus.text =
                        getString(R.string.status_error, e.message ?: "unknown error")
                }
            }
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }
}
