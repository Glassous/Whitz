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
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.navigation
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.glassous.whitz.feature.auth.AuthViewModel
import com.glassous.whitz.feature.auth.ForgotPasswordScreen
import com.glassous.whitz.feature.auth.LoginScreen
import com.glassous.whitz.feature.auth.RegisterScreen
import com.glassous.whitz.feature.chat.ChatScreen
import com.glassous.whitz.feature.chat.ChatViewModel
import com.glassous.whitz.feature.chat.LibraryScreen
import com.glassous.whitz.feature.chat.TaskDetailScreen
import com.glassous.whitz.feature.posts.PostComposeScreen
import com.glassous.whitz.feature.posts.PostsGuideScreen
import com.glassous.whitz.feature.posts.PostsScreen
import com.glassous.whitz.feature.schedules.ScheduleEditorScreen
import com.glassous.whitz.feature.schedules.SchedulesScreen
import com.glassous.whitz.feature.settings.AddMemoryScreen
import com.glassous.whitz.feature.settings.AssistantSettingsScreen
import com.glassous.whitz.feature.settings.CreateSkillScreen
import com.glassous.whitz.feature.settings.DevicesSettingsScreen
import com.glassous.whitz.feature.settings.FeedbackSettingsScreen
import com.glassous.whitz.feature.settings.GithubSkillInstallScreen
import com.glassous.whitz.feature.settings.LibrarySettingsScreen
import com.glassous.whitz.feature.settings.MembershipSettingsScreen
import com.glassous.whitz.feature.settings.MemorySettingsScreen
import com.glassous.whitz.feature.settings.OneHandedSettingsScreen
import com.glassous.whitz.feature.settings.PasswordSettingsScreen
import com.glassous.whitz.feature.settings.PersonaSettingsScreen
import com.glassous.whitz.feature.settings.ProfileSettingsScreen
import com.glassous.whitz.feature.settings.SettingsHomeScreen
import com.glassous.whitz.feature.settings.SettingsRoutes
import com.glassous.whitz.feature.settings.SettingsViewModel
import com.glassous.whitz.feature.settings.SkillsSettingsScreen
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
            val oneHandedConfig by container.oneHandedConfig.collectAsState()
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

            WhitzTheme(
                preference = themePref,
                oneHandedConfig = oneHandedConfig,
            ) {
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
                onOpenSettings = { navController.navigate(SettingsRoutes.GRAPH) },
                onOpenLibrary = { navController.navigate("library") },
                onOpenSchedules = { navController.navigate("schedules") },
                onOpenPosts = { navController.navigate("posts") },
                onOpenTaskDetails = { tab -> navController.navigate("task_details?tab=$tab") },
            )
        }
        composable("posts") { backStackEntry ->
            val chatEntry = remember(backStackEntry) {
                runCatching { navController.getBackStackEntry("chat") }.getOrNull()
            }
            if (chatEntry != null) {
                val chatVm: ChatViewModel = viewModel(chatEntry, factory = factory)
                PostsScreen(
                    vm = chatVm,
                    onOpenCompose = { navController.navigate("posts_compose") },
                    onOpenGuide = { navController.navigate("posts_guide") },
                    onOpenMemorySettings = { navController.navigate(SettingsRoutes.MEMORY) },
                    onOpenConversation = { convId, _ ->
                        chatVm.refreshConversations()
                        chatVm.openConversation(convId)
                        navController.popBackStack("chat", inclusive = false)
                    },
                    onBack = { navController.popBackStack() },
                )
            }
        }
        composable("posts_compose") { backStackEntry ->
            val chatEntry = remember(backStackEntry) {
                runCatching { navController.getBackStackEntry("chat") }.getOrNull()
            }
            if (chatEntry != null) {
                val chatVm: ChatViewModel = viewModel(chatEntry, factory = factory)
                PostComposeScreen(
                    vm = chatVm,
                    onPublished = { navController.popBackStack() },
                    onBack = { navController.popBackStack() },
                )
            }
        }
        composable("posts_guide") { backStackEntry ->
            val chatEntry = remember(backStackEntry) {
                runCatching { navController.getBackStackEntry("chat") }.getOrNull()
            }
            if (chatEntry != null) {
                val chatVm: ChatViewModel = viewModel(chatEntry, factory = factory)
                PostsGuideScreen(
                    vm = chatVm,
                    onOpenMemorySettings = { navController.navigate(SettingsRoutes.MEMORY) },
                    onBack = { navController.popBackStack() },
                )
            }
        }
        composable("library") { backStackEntry ->
            val chatEntry = remember(backStackEntry) {
                runCatching { navController.getBackStackEntry("chat") }.getOrNull()
            }
            if (chatEntry != null) {
                val chatVm: ChatViewModel = viewModel(chatEntry, factory = factory)
                LibraryScreen(
                    vm = chatVm,
                    onBack = { navController.popBackStack() },
                )
            }
        }
        composable("schedules") { backStackEntry ->
            val chatEntry = remember(backStackEntry) {
                runCatching { navController.getBackStackEntry("chat") }.getOrNull()
            }
            if (chatEntry != null) {
                val chatVm: ChatViewModel = viewModel(chatEntry, factory = factory)
                SchedulesScreen(
                    vm = chatVm,
                    onOpenEditor = { taskId ->
                        if (taskId.isNullOrBlank()) {
                            navController.navigate("schedule_editor")
                        } else {
                            navController.navigate("schedule_editor?taskId=$taskId")
                        }
                    },
                    onOpenConversation = { convId ->
                        chatVm.openConversation(convId)
                        navController.popBackStack("chat", inclusive = false)
                    },
                    onBack = { navController.popBackStack() },
                )
            }
        }
        composable(
            route = "schedule_editor?taskId={taskId}",
            arguments = listOf(
                navArgument("taskId") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { backStackEntry ->
            val taskId = backStackEntry.arguments?.getString("taskId")
            val chatEntry = remember(backStackEntry) {
                runCatching { navController.getBackStackEntry("chat") }.getOrNull()
            }
            if (chatEntry != null) {
                val chatVm: ChatViewModel = viewModel(chatEntry, factory = factory)
                ScheduleEditorScreen(
                    vm = chatVm,
                    taskId = taskId,
                    onSaved = { navController.popBackStack() },
                    onBack = { navController.popBackStack() },
                )
            }
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
        navigation(
            route = SettingsRoutes.GRAPH,
            startDestination = SettingsRoutes.HOME,
        ) {
            composable(SettingsRoutes.HOME) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    SettingsHomeScreen(
                        vm = vm,
                        onNavigateRoute = { route -> navController.navigate(route) },
                        onBackToChat = { navController.popBackStack() },
                        onLoggedOut = {
                            navController.navigate("login") {
                                popUpTo(0) { inclusive = true }
                            }
                        },
                    )
                }
            }
            composable(SettingsRoutes.PROFILE) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    ProfileSettingsScreen(
                        vm = vm,
                        onOpenPassword = { navController.navigate(SettingsRoutes.PASSWORD) },
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.PASSWORD) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    PasswordSettingsScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.LIBRARY) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    LibrarySettingsScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.MEMORY) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    MemorySettingsScreen(
                        vm = vm,
                        onOpenAddMemory = { navController.navigate(SettingsRoutes.MEMORY_ADD) },
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.MEMORY_ADD) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    AddMemoryScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.SKILLS) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    SkillsSettingsScreen(
                        vm = vm,
                        onOpenCreateSkill = { navController.navigate(SettingsRoutes.SKILLS_CREATE) },
                        onOpenGithubInstall = { navController.navigate(SettingsRoutes.SKILLS_GITHUB) },
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.SKILLS_CREATE) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    CreateSkillScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.SKILLS_GITHUB) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    GithubSkillInstallScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.MEMBERSHIP) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    MembershipSettingsScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.ASSISTANT) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    AssistantSettingsScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.PERSONA) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    PersonaSettingsScreen(
                        vm = vm,
                        onOpenEditAssistant = { navController.navigate(SettingsRoutes.ASSISTANT) },
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.DEVICES) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    DevicesSettingsScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.FEEDBACK) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    FeedbackSettingsScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
            composable(SettingsRoutes.ONE_HANDED) { entry ->
                rememberSharedSettingsVm(navController, entry, factory)?.let { vm ->
                    OneHandedSettingsScreen(
                        vm = vm,
                        onBack = { navController.popBackStack() },
                    )
                }
            }
        }
    }
}

@Composable
private fun rememberSharedSettingsVm(
    navController: NavController,
    entry: NavBackStackEntry,
    factory: ViewModelProvider.Factory,
): SettingsViewModel? {
    val parentEntry = remember(entry) {
        runCatching { navController.getBackStackEntry(SettingsRoutes.GRAPH) }.getOrNull()
    } ?: return null
    return viewModel(parentEntry, factory = factory)
}
