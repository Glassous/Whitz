package com.glassous.whitz.feature.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MediumFlexibleTopAppBar
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.glassous.whitz.ui.theme.WhitzCollapsibleTopBarLayout
import com.glassous.whitz.ui.theme.WhitzOneHandedBackDock

@Composable
fun LibraryScreen(
    vm: ChatViewModel,
    onBack: () -> Unit,
) {
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) {
        vm.library.loadFiles()
    }

    WhitzCollapsibleTopBarLayout(
        title = "资料库",
        onBack = onBack,
        overlay = { WhitzOneHandedBackDock(onBack = onBack) },
    ) { topPadding ->
        LibraryPane(
            controller = vm.library,
            bottomPadding = navBottom + 24.dp,
            modifier = Modifier
                .widthIn(max = 840.dp)
                .fillMaxSize()
                .padding(top = topPadding),
        )
    }
}
