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
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.glassous.whitz.feature.auth.AuthViewModel
import com.glassous.whitz.feature.auth.ForgotPasswordScreen
import com.glassous.whitz.feature.auth.LoginScreen
import com.glassous.whitz.feature.auth.RegisterScreen
import com.glassous.whitz.feature.chat.ChatScreen
import com.glassous.whitz.feature.chat.ChatViewModel
import com.glassous.whitz.feature.chat.TaskDetailScreen
import com.glassous.whitz.feature.settings.SettingsRootScreen
import com.glassous.whitz.feature.settings.SettingsViewModel
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
    val user by container.authManager.user.collectAsState()

    LaunchedEffect(Unit) {
        container.authManager.init { container.network.api.getMe() }
    }

    val navController = rememberNavController()
    val factory = ContainerVmFactory(container)
    val startDestination = remember { if (user != null) "chat" else "login" }

    LaunchedEffect(user) {
        val currentRoute = navController.currentBackStackEntry?.destination?.route
        if (user == null && currentRoute != null && currentRoute !in setOf("login", "register", "forgot")) {
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
                onOpenTaskDetails = { tab -> navController.navigate("task_details?tab=$tab") },
            )
        }
        composable(
            route = "task_details?tab={tab}",
            arguments = listOf(
                navArgument("tab") {
                    type = NavType.IntType
                    defaultValue = 0
                },
            ),
        ) { backStackEntry ->
            val initialTab = backStackEntry.arguments?.getInt("tab") ?: 0
            val chatEntry = remember(backStackEntry) {
                runCatching { navController.getBackStackEntry("chat") }.getOrNull()
            }
            if (chatEntry != null) {
                val chatVm: ChatViewModel = viewModel(chatEntry, factory = factory)
                TaskDetailScreen(
                    vm = chatVm,
                    initialTab = initialTab,
                    onBack = { navController.popBackStack() },
                )
            }
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
