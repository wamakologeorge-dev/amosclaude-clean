package com.amosclaudai

import android.os.Bundle
import android.view.inputmethod.EditorInfo
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.amosclaudai.adapter.ChatAdapter
import com.amosclaudai.api.AmosclaudApiClient
import com.amosclaudai.databinding.ActivityAiChatBinding
import com.amosclaudai.model.ChatMessage
import kotlinx.coroutines.launch

class AiChatActivity : AppCompatActivity() {
    private lateinit var binding: ActivityAiChatBinding
    private lateinit var adapter: ChatAdapter
    private val messages = mutableListOf<ChatMessage>()
    private var sessionId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityAiChatBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.apply {
            title = getString(R.string.title_ai_chat)
            setDisplayHomeAsUpEnabled(true)
        }

        sessionId = getSharedPreferences("amosclaud_chat", MODE_PRIVATE).getString("session_id", null)
        setupRecyclerView()
        setupInput()
        appendMessage(
            ChatMessage.Role.ASSISTANT,
            "Hello! I’m Amosclaud. Ask me to inspect, explain, build, test, deploy, or monitor your connected projects.",
        )
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }

    private fun setupRecyclerView() {
        adapter = ChatAdapter(messages)
        binding.rvMessages.apply {
            layoutManager = LinearLayoutManager(this@AiChatActivity).also { it.stackFromEnd = true }
            adapter = this@AiChatActivity.adapter
        }
    }

    private fun setupInput() {
        binding.etMessage.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendMessage()
                true
            } else false
        }
        binding.btnSend.setOnClickListener { sendMessage() }
    }

    private fun sendMessage() {
        val text = binding.etMessage.text?.toString()?.trim().orEmpty()
        if (text.isEmpty()) return

        binding.etMessage.text?.clear()
        appendMessage(ChatMessage.Role.USER, text)
        setLoading(true)

        lifecycleScope.launch {
            try {
                val response = AmosclaudApiClient.sendMessage(this@AiChatActivity, text, sessionId)
                if (response.sessionId.isNotBlank()) {
                    sessionId = response.sessionId
                    getSharedPreferences("amosclaud_chat", MODE_PRIVATE)
                        .edit()
                        .putString("session_id", response.sessionId)
                        .apply()
                }
                appendMessage(ChatMessage.Role.ASSISTANT, response.reply)
            } catch (error: AmosclaudApiClient.ApiException) {
                if (error.statusCode == 401) {
                    AmosclaudApiClient.clearSession(this@AiChatActivity)
                    appendMessage(ChatMessage.Role.ASSISTANT, "Your session expired. Return to the home screen and sign in again.")
                } else {
                    appendMessage(ChatMessage.Role.ASSISTANT, "Amosclaud could not complete that request: ${error.message}")
                }
            } catch (_: Exception) {
                appendMessage(
                    ChatMessage.Role.ASSISTANT,
                    "The Android app could not reach Amosclaud. Check your internet connection and server address, then try again.",
                )
            } finally {
                setLoading(false)
                binding.etMessage.requestFocus()
            }
        }
    }

    private fun appendMessage(role: ChatMessage.Role, content: String) {
        messages.add(ChatMessage(role, content))
        adapter.notifyItemInserted(messages.size - 1)
        binding.rvMessages.scrollToPosition(messages.size - 1)
    }

    private fun setLoading(loading: Boolean) {
        binding.progressBar.isVisible = loading
        binding.btnSend.isEnabled = !loading
        binding.etMessage.isEnabled = !loading
    }
}
