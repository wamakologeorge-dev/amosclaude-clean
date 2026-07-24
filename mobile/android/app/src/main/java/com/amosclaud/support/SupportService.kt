package com.amosclaud.support

import android.app.Service
import android.content.Intent
import android.os.IBinder

/**
 * Native support-service entry point for Amosclaud mobile operations.
 *
 * This service intentionally contains no GitHub credentials, GitHub App private key,
 * API token, or production secret. Privileged operations must remain server-side.
 */
class SupportService : Service() {
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Future integration point:
        // 1. authenticate the user with the Amosclaud backend,
        // 2. obtain short-lived user-scoped access,
        // 3. receive repository/support/approval events,
        // 4. surface notifications and approval requests to the user.
        stopSelf(startId)
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
