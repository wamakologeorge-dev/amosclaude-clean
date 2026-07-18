package com.amosclaudai.model

/** API response for POST /api/chat */
data class ChatResponse(
    val reply: String,
    val sessionId: String,
    val timestamp: String,
)
