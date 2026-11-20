package com.glassous.whitz.feature.auth

import android.util.Patterns
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glassous.whitz.AppContainer
import com.glassous.whitz.core.network.EmailCodeRequest
import com.glassous.whitz.core.network.LoginCodeRequest
import com.glassous.whitz.core.network.LoginRequest
import com.glassous.whitz.core.network.RegisterRequest
import com.glassous.whitz.core.network.ResetPasswordRequest
import com.glassous.whitz.core.network.extractErrorMessage
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class AuthUiState(
    val loading: Boolean = false,
    val sendingCode: Boolean = false,
    val cooldown: Int = 0,
    val codeNotice: String? = null,
    val error: String? = null,
)

class AuthViewModel(
    private val container: AppContainer,
) : ViewModel() {
    private val _ui = MutableStateFlow(AuthUiState())
    val ui: StateFlow<AuthUiState> = _ui.asStateFlow()

    val logoutNotice = container.authManager.logoutNotice

    private var cooldownJob: Job? = null

    fun clearError() {
        _ui.value = _ui.value.copy(error = null)
    }

    fun clearNotice() {
        _ui.value = _ui.value.copy(codeNotice = null)
    }

    fun dismissLogoutNotice() {
        container.authManager.clearLogoutNotice()
    }

    fun isValidEmail(email: String): Boolean {
        val trimmed = email.trim()
        return trimmed.isNotEmpty() && Patterns.EMAIL_ADDRESS.matcher(trimmed).matches()
    }

    fun sendEmailCode(email: String, purpose: String) {
        val trimmed = email.trim()
        if (!isValidEmail(trimmed)) {
            _ui.value = _ui.value.copy(error = "请输入有效的邮箱地址")
            return
        }
        if (_ui.value.sendingCode || _ui.value.cooldown > 0) return

        viewModelScope.launch {
            _ui.value = _ui.value.copy(sendingCode = true, error = null, codeNotice = null)
            try {
                val resp = container.network.api.sendEmailCode(EmailCodeRequest(trimmed, purpose))
                _ui.value = _ui.value.copy(
                    sendingCode = false,
                    codeNotice = resp.message.ifBlank { "验证码已发送至 $trimmed" },
                )
                startCooldown(resp.cooldown.coerceAtLeast(1))
            } catch (t: Throwable) {
                _ui.value = _ui.value.copy(
                    sendingCode = false,
                    error = extractErrorMessage(t, "发送验证码失败"),
                )
            }
        }
    }

    private fun startCooldown(seconds: Int) {
        cooldownJob?.cancel()
        cooldownJob = viewModelScope.launch {
            var remaining = seconds
            while (remaining > 0) {
                _ui.value = _ui.value.copy(cooldown = remaining)
                delay(1000L)
                remaining--
            }
            _ui.value = _ui.value.copy(cooldown = 0)
        }
    }

    fun loginWithPassword(identifier: String, password: String, onSuccess: () -> Unit) {
        val acct = identifier.trim()
        if (acct.isEmpty()) {
            _ui.value = _ui.value.copy(error = "请输入邮箱或用户名")
            return
        }
        if (password.isEmpty()) {
            _ui.value = _ui.value.copy(error = "请输入登录密码")
            return
        }
        viewModelScope.launch {
            _ui.value = _ui.value.copy(loading = true, error = null)
            try {
                val auth = container.network.api.login(LoginRequest(acct, password))
                container.authManager.applySession(auth)
                _ui.value = _ui.value.copy(loading = false)
                onSuccess()
            } catch (t: Throwable) {
                _ui.value = _ui.value.copy(loading = false, error = extractErrorMessage(t, "登录失败"))
            }
        }
    }

    fun loginWithCode(email: String, code: String, onSuccess: () -> Unit) {
        val acct = email.trim()
        val trimmedCode = code.trim()
        if (!isValidEmail(acct)) {
            _ui.value = _ui.value.copy(error = "请输入有效的邮箱地址")
            return
        }
        if (trimmedCode.isEmpty()) {
            _ui.value = _ui.value.copy(error = "请输入邮箱验证码")
            return
        }
        viewModelScope.launch {
            _ui.value = _ui.value.copy(loading = true, error = null)
            try {
                val auth = container.network.api.loginWithCode(LoginCodeRequest(acct, trimmedCode))
                container.authManager.applySession(auth)
                _ui.value = _ui.value.copy(loading = false)
                onSuccess()
            } catch (t: Throwable) {
                _ui.value = _ui.value.copy(loading = false, error = extractErrorMessage(t, "登录失败"))
            }
        }
    }

    fun register(email: String, code: String, displayName: String, password: String, onSuccess: () -> Unit) {
        val trimmedEmail = email.trim()
        val trimmedCode = code.trim()
        val trimmedName = displayName.trim()
        if (!isValidEmail(trimmedEmail)) {
            _ui.value = _ui.value.copy(error = "请输入有效的邮箱地址")
            return
        }
        if (trimmedCode.isEmpty()) {
            _ui.value = _ui.value.copy(error = "请输入邮箱验证码")
            return
        }
        if (trimmedName.isEmpty()) {
            _ui.value = _ui.value.copy(error = "请输入昵称")
            return
        }
        if (password.length < 6) {
            _ui.value = _ui.value.copy(error = "密码长度至少 6 位")
            return
        }
        viewModelScope.launch {
            _ui.value = _ui.value.copy(loading = true, error = null)
            try {
                val auth = container.network.api.register(
                    RegisterRequest(trimmedEmail, trimmedCode, password, trimmedName)
                )
                container.authManager.applySession(auth)
                _ui.value = _ui.value.copy(loading = false)
                onSuccess()
            } catch (t: Throwable) {
                _ui.value = _ui.value.copy(loading = false, error = extractErrorMessage(t, "注册失败"))
            }
        }
    }

    fun resetPassword(email: String, code: String, newPassword: String, onSuccess: () -> Unit) {
        val trimmedEmail = email.trim()
        val trimmedCode = code.trim()
        if (!isValidEmail(trimmedEmail)) {
            _ui.value = _ui.value.copy(error = "请输入有效的邮箱地址")
            return
        }
        if (trimmedCode.isEmpty()) {
            _ui.value = _ui.value.copy(error = "请输入邮箱验证码")
            return
        }
        if (newPassword.length < 6) {
            _ui.value = _ui.value.copy(error = "新密码长度至少 6 位")
            return
        }
        viewModelScope.launch {
            _ui.value = _ui.value.copy(loading = true, error = null)
            try {
                val resp = container.network.api.resetPassword(
                    ResetPasswordRequest(trimmedEmail, trimmedCode, newPassword)
                )
                if (!resp.isSuccessful) {
                    val err = resp.errorBody()?.string()
                    throw com.glassous.whitz.core.network.ApiException(resp.code(), err ?: "重置密码失败")
                }
                _ui.value = _ui.value.copy(loading = false)
                onSuccess()
            } catch (t: Throwable) {
                _ui.value = _ui.value.copy(loading = false, error = extractErrorMessage(t, "重置密码失败"))
            }
        }
    }
}
