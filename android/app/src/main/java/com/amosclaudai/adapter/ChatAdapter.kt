package com.amosclaudai.adapter

import android.view.Gravity
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.recyclerview.widget.RecyclerView
import com.amosclaudai.R
import com.amosclaudai.databinding.ItemChatMessageBinding
import com.amosclaudai.model.ChatMessage

/**
 * RecyclerView adapter for chat messages.
 * User messages are right-aligned; assistant messages are left-aligned.
 */
class ChatAdapter(
    private val messages: List<ChatMessage>,
) : RecyclerView.Adapter<ChatAdapter.MessageViewHolder>() {

    inner class MessageViewHolder(
        private val binding: ItemChatMessageBinding,
    ) : RecyclerView.ViewHolder(binding.root) {

        fun bind(message: ChatMessage) {
            binding.tvMessage.text = message.content

            val isUser = message.role == ChatMessage.Role.USER

            // Swap background and gravity
            binding.tvMessage.setBackgroundResource(
                if (isUser) R.drawable.bg_bubble_user else R.drawable.bg_bubble_assistant
            )

            val params = binding.tvMessage.layoutParams as FrameLayout.LayoutParams
            params.gravity = if (isUser) Gravity.END else Gravity.START
            binding.tvMessage.layoutParams = params

            binding.tvMessage.setTextColor(
                binding.root.context.getColor(
                    if (isUser) R.color.bubble_user_text else R.color.bubble_assistant_text
                )
            )
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): MessageViewHolder {
        val binding = ItemChatMessageBinding.inflate(
            LayoutInflater.from(parent.context), parent, false
        )
        return MessageViewHolder(binding)
    }

    override fun onBindViewHolder(holder: MessageViewHolder, position: Int) {
        holder.bind(messages[position])
    }

    override fun getItemCount() = messages.size
}
