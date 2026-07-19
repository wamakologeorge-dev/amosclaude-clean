package com.amosclaudai

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.amosclaudai.api.AmosclaudApiClient
import com.amosclaudai.databinding.ActivitySettingsBinding
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import kotlinx.coroutines.launch

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
            if (url.isEmpty()) {
                binding.etApiUrl.error = getString(R.string.error_url_required)
                return@setOnClickListener
            }
            AmosclaudApiClient.saveBaseUrl(this, url)
            binding.tvConnectionStatus.text = getString(R.string.status_testing)
            lifecycleScope.launch {
                val ok = AmosclaudApiClient.testConnection(this@SettingsActivity)
                binding.tvConnectionStatus.text = if (ok) {
                    getString(R.string.status_connected)
                } else {
                    getString(R.string.status_failed)
                }
            }
        }

        binding.btnDeleteAccount.setOnClickListener {
            val email = binding.etDeleteEmail.text?.toString()?.trim().orEmpty()
            if (email.isBlank()) {
                binding.deleteEmailLayout.error = getString(R.string.error_delete_email_required)
                return@setOnClickListener
            }
            binding.deleteEmailLayout.error = null
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.delete_account_title)
                .setMessage(R.string.delete_account_warning)
                .setNegativeButton(R.string.btn_cancel, null)
                .setPositiveButton(R.string.btn_confirm_delete) { _, _ -> deleteAccount(email) }
                .show()
        }
    }

    private fun deleteAccount(email: String) {
        binding.btnDeleteAccount.isEnabled = false
        val password = binding.etDeletePassword.text?.toString()
        lifecycleScope.launch {
            try {
                AmosclaudApiClient.deleteAccount(this@SettingsActivity, email, password)
                Toast.makeText(this@SettingsActivity, R.string.account_deleted, Toast.LENGTH_LONG).show()
                startActivity(Intent(this@SettingsActivity, AuthActivity::class.java).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                })
                finish()
            } catch (error: Exception) {
                Toast.makeText(
                    this@SettingsActivity,
                    getString(R.string.status_error, error.message ?: "Unknown error"),
                    Toast.LENGTH_LONG,
                ).show()
                binding.btnDeleteAccount.isEnabled = true
            }
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }
}
