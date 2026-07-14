package com.amosclaudai

import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.amosclaudai.api.AmosclaudApiClient
import com.google.android.material.card.MaterialCardView
import kotlinx.coroutines.launch

class AuthActivity : AppCompatActivity() {
    private lateinit var title: TextView
    private lateinit var message: TextView
    private lateinit var nameInput: EditText
    private lateinit var emailInput: EditText
    private lateinit var passwordInput: EditText
    private lateinit var codeInput: EditText
    private lateinit var primaryButton: Button
    private lateinit var switchButton: Button
    private lateinit var progress: ProgressBar
    private var mode = Mode.LOGIN

    private enum class Mode { LOGIN, SIGNUP, VERIFY }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContent())
        render()
    }

    private fun buildContent(): View {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(28), dp(20), dp(28))
        }
        root.addView(TextView(this).apply {
            text = "Amosclaud"
            textSize = 30f
            setTypeface(typeface, android.graphics.Typeface.BOLD)
        })
        root.addView(TextView(this).apply {
            text = "Native Android access"
            textSize = 14f
            alpha = .65f
        })

        val card = MaterialCardView(this).apply {
            radius = dp(18).toFloat()
            cardElevation = dp(3).toFloat()
            setContentPadding(dp(20), dp(20), dp(20), dp(20))
            val params = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
            params.topMargin = dp(28)
            layoutParams = params
        }
        val form = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        title = TextView(this).apply { textSize = 24f; setTypeface(typeface, android.graphics.Typeface.BOLD) }
        message = TextView(this).apply { textSize = 14f; alpha = .75f }
        nameInput = field("Full name")
        emailInput = field("Email address").apply { inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS }
        passwordInput = field("Password").apply { inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD }
        codeInput = field("6-digit verification code").apply { inputType = InputType.TYPE_CLASS_NUMBER }
        primaryButton = Button(this).apply { setOnClickListener { submit() } }
        switchButton = Button(this).apply { setOnClickListener { switchMode() } }
        progress = ProgressBar(this).apply { visibility = View.GONE }

        listOf<View>(title, message, nameInput, emailInput, passwordInput, codeInput, primaryButton, switchButton, progress).forEach {
            val params = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
            params.topMargin = dp(12)
            form.addView(it, params)
        }
        card.addView(form)
        root.addView(card)
        return root
    }

    private fun field(hintText: String) = EditText(this).apply {
        hint = hintText
        setSingleLine(true)
    }

    private fun render() {
        when (mode) {
            Mode.LOGIN -> {
                title.text = "Sign in"
                message.text = "Use the account you created on Amosclaud. Your session will be saved securely on this device."
                nameInput.visibility = View.GONE
                codeInput.visibility = View.GONE
                primaryButton.text = "Sign in"
                switchButton.text = "Create an account"
            }
            Mode.SIGNUP -> {
                title.text = "Create account"
                message.text = "We will email you a verification code before creating the account."
                nameInput.visibility = View.VISIBLE
                codeInput.visibility = View.GONE
                primaryButton.text = "Send verification code"
                switchButton.text = "Back to sign in"
            }
            Mode.VERIFY -> {
                title.text = "Verify account"
                message.text = "Enter the 6-digit code sent to ${emailInput.text}."
                nameInput.visibility = View.GONE
                codeInput.visibility = View.VISIBLE
                primaryButton.text = "Verify and continue"
                switchButton.text = "Start over"
            }
        }
    }

    private fun switchMode() {
        mode = when (mode) {
            Mode.LOGIN -> Mode.SIGNUP
            Mode.SIGNUP -> Mode.LOGIN
            Mode.VERIFY -> Mode.SIGNUP
        }
        message.text = ""
        render()
    }

    private fun submit() {
        val name = nameInput.text.toString().trim()
        val email = emailInput.text.toString().trim()
        val password = passwordInput.text.toString()
        val code = codeInput.text.toString().trim()

        if (email.isBlank() || password.isBlank()) {
            message.text = "Enter your email and password."
            return
        }
        if (mode == Mode.SIGNUP && (name.length < 2 || password.length < 10)) {
            message.text = "Enter your full name and a password with at least 10 characters."
            return
        }
        if (mode == Mode.VERIFY && code.length != 6) {
            message.text = "Enter the 6-digit verification code."
            return
        }

        setBusy(true)
        lifecycleScope.launch {
            try {
                when (mode) {
                    Mode.LOGIN -> AmosclaudApiClient.login(this@AuthActivity, email, password)
                    Mode.SIGNUP -> {
                        AmosclaudApiClient.requestRegistrationCode(this@AuthActivity, name, email, password)
                        mode = Mode.VERIFY
                        render()
                        return@launch
                    }
                    Mode.VERIFY -> AmosclaudApiClient.verifyRegistration(this@AuthActivity, email, password, code)
                }
                startActivity(Intent(this@AuthActivity, MainActivity::class.java))
                finish()
            } catch (error: AmosclaudApiClient.ApiException) {
                message.text = error.message
            } catch (_: Exception) {
                message.text = "The Android app could not reach Amosclaud. Check your connection and server address."
            } finally {
                setBusy(false)
            }
        }
    }

    private fun setBusy(busy: Boolean) {
        progress.visibility = if (busy) View.VISIBLE else View.GONE
        primaryButton.isEnabled = !busy
        switchButton.isEnabled = !busy
        emailInput.isEnabled = !busy
        passwordInput.isEnabled = !busy
        nameInput.isEnabled = !busy
        codeInput.isEnabled = !busy
    }
}
