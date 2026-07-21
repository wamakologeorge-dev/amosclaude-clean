package com.amosclaud.support

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val status = findViewById<TextView>(R.id.statusText)
        val start = findViewById<Button>(R.id.startSupportButton)
        val approvals = findViewById<Button>(R.id.approvalsButton)

        status.text = "Amosclaud Support is ready.\nGitHub approvals and support events will appear here once the secure backend connection is configured."

        start.setOnClickListener {
            requestNotificationPermissionIfNeeded()
            startService(Intent(this, SupportService::class.java))
            status.text = "Support service started. Waiting for secure Amosclaud backend events."
        }

        approvals.setOnClickListener {
            status.text = "Approval center ready. Sensitive actions remain human-controlled through Amosclaud approval issues until backend sign-in is connected."
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1001)
        }
    }
}
