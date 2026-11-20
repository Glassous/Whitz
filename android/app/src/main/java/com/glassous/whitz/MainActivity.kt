package com.glassous.whitz

import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.glassous.whitz.feature.auth.AuthViewModel
import com.glassous.whitz.feature.auth.ForgotPasswordScreen
import com.glassous.whitz.feature.auth.LoginScreen
import com.glassous.whitz.feature.auth.RegisterScreen
import com.glassous.whitz.feature.chat.ChatScreen
import com.glassous.whitz.feature.chat.ChatViewModel
import com.glassous.whitz.feature.settings.SettingsRootScreen
import com.glassous.whitz.feature.settings.SettingsViewModel
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzLogoMark
import com.glassous.whitz.ui.theme.WhitzTheme
import com.glassous.whitz.ui.theme.isWhitzDarkTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        window.isNavigationBarContrastEnforced = false
        val container = (application as WhitzApplication).container

        setContent {
            val themePref by container.themePreference.collectAsState()
            val dark = isWhitzDarkTheme(themePref)

            SideEffect {
                val barStyle = if (dark) {
                    SystemBarStyle.dark(Color.TRANSPARENT)
                } else {
                    SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
                }
                enableEdgeToEdge(
                    statusBarStyle = barStyle,
                    navigationBarStyle = barStyle,
                )
                window.isNavigationBarContrastEnforced = false
            }

            WhitzTheme(preference = themePref) {
                WhitzRoot(container = container)
            }
        }
    }
}

private class ContainerVmFactory(
    private val container: AppContainer,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return when {
            modelClass.isAssignableFrom(AuthViewModel::class.java) -> AuthViewModel(container) as T
            modelClass.isAssignableFrom(ChatViewModel::class.java) -> ChatViewModel(container) as T
            modelClass.isAssignableFrom(SettingsViewModel::class.java) -> SettingsViewModel(container) as T
            else -> throw IllegalArgumentException("Unknown ViewModel: ${modelClass.name}")
        }
    }
}

@Composable
private fun WhitzRoot(container: AppContainer) {
    val ready by container.authManager.ready.collectAsState()
    val user by container.authManager.user.collectAsState()

    LaunchedEffect(Unit) {
        container.authManager.init { container.network.api.getMe() }
    }

    if (!ready) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(LocalWhitzColors.current.canvas),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                WhitzLogoMark(modifier = Modifier.size(48.dp))
                Spacer(modifier = Modifier.height(20.dp))
                WhitzLoadingIndicator(size = 28.dp)
            }
        }
        return
    }

    val navController = rememberNavController()
    val factory = ContainerVmFactory(container)
    val startDestination = if (user != null) "chat" else "login"

    LaunchedEffect(user) {
        val currentRoute = navController.currentBackStackEntry?.destination?.route
        if (user == null && currentRoute in setOf("chat", "settings")) {
            navController.navigate("login") {
                popUpTo(0) { inclusive = true }
            }
        } else if (user != null && currentRoute in setOf("login", "register", "forgot")) {
            navController.navigate("chat") {
                popUpTo(0) { inclusive = true }
            }
        }
    }

    NavHost(
        navController = navController,
        startDestination = startDestination,
        enterTransition = { fadeIn(tween(220)) + slideInHorizontally(tween(260)) { it / 16 } },
        exitTransition = { fadeOut(tween(180)) },
        popEnterTransition = { fadeIn(tween(220)) },
        popExitTransition = { fadeOut(tween(180)) + slideOutHorizontally(tween(240)) { it / 16 } },
    ) {
        composable("login") {
            val authVm: AuthViewModel = viewModel(factory = factory)
            LoginScreen(
                vm = authVm,
                onLoginSuccess = {
                    navController.navigate("chat") {
                        popUpTo(0) { inclusive = true }
                    }
                },
                onNavigateRegister = { navController.navigate("register") },
                onNavigateForgot = { navController.navigate("forgot") },
            )
        }
        composable("register") {
            val authVm: AuthViewModel = viewModel(factory = factory)
            RegisterScreen(
                vm = authVm,
                onRegisterSuccess = {
                    navController.navigate("chat") {
                        popUpTo(0) { inclusive = true }
                    }
                },
                onBack = { navController.popBackStack() },
            )
        }
        composable("forgot") {
            val authVm: AuthViewModel = viewModel(factory = factory)
            ForgotPasswordScreen(
                vm = authVm,
                onResetSuccess = { navController.popBackStack() },
                onBack = { navController.popBackStack() },
            )
        }
        composable("chat") {
            val chatVm: ChatViewModel = viewModel(factory = factory)
            ChatScreen(
                vm = chatVm,
                onOpenSettings = { navController.navigate("settings") },
            )
        }
        composable("settings") {
            val settingsVm: SettingsViewModel = viewModel(factory = factory)
            SettingsRootScreen(
                vm = settingsVm,
                onBackToChat = { navController.popBackStack() },
                onLoggedOut = {
                    navController.navigate("login") {
                        popUpTo(0) { inclusive = true }
                    }
                },
            )
        }
    }
}
