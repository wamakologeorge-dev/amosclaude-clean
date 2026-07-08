package com.amosclaudai.model

/**
 * Represents a single message in the AI chat conversation.
 */
data class ChatMessage(
    val role: Role,
    val content: String,
    val timestamp: Long = System.currentTimeMillis(),
) {
    enum class Role { USER, ASSISTANT }
}
