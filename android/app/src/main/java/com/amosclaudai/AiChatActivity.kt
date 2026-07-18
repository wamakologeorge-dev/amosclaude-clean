package com.amosclaudai

import android.os.Bundle
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.amosclaudai.adapter.ChatAdapter
import com.amosclaudai.api.AmosclaudApiClient
import com.amosclaudai.databinding.ActivityAiChatBinding
import com.amosclaudai.model.ChatMessage
import kotlinx.coroutines.launch

/**
 * AI Chat screen.
 * Sends messages to the Amosclaud-AI backend and displays replies in a RecyclerView.
 */
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

        setupRecyclerView()
        setupInput()

        // Welcome message
        appendMessage(ChatMessage.Role.ASSISTANT,
            "Hello! I'm Amosclaud-AI 🤖 — your intelligent CI/CD & DevOps assistant.\n\n" +
            "I can help with deployments, tests, database management, code analysis, and Git operations.")
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }

    private fun setupRecyclerView() {
        adapter = ChatAdapter(messages)
        binding.rvMessages.apply {
            layoutManager = LinearLayoutManager(this@AiChatActivity).also {
                it.stackFromEnd = true
            }
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
        val text = binding.etMessage.text?.toString()?.trim() ?: return
        if (text.isEmpty()) return

        binding.etMessage.text?.clear()
        hideKeyboard()

        appendMessage(ChatMessage.Role.USER, text)
        setLoading(true)

        val apiUrl = AmosclaudApiClient.getBaseUrl(this)

        lifecycleScope.launch {
            try {
                val response = AmosclaudApiClient.sendMessage(apiUrl, text, sessionId)
                sessionId = response.sessionId
                appendMessage(ChatMessage.Role.ASSISTANT, response.reply)
            } catch (e: Exception) {
                appendMessage(ChatMessage.Role.ASSISTANT,
                    "⚠️ Could not reach the server. Please check your Settings and ensure the backend is running.\n\nError: ${e.message}")
            } finally {
                setLoading(false)
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
    }

    private fun hideKeyboard() {
        val imm = getSystemService(InputMethodManager::class.java)
        imm.hideSoftInputFromWindow(binding.etMessage.windowToken, 0)
    }
}
