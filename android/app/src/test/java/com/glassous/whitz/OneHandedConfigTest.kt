package com.glassous.whitz

import com.glassous.whitz.core.model.OneHandedConfig
import com.glassous.whitz.core.model.OneHandedSide
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class OneHandedConfigTest {
    @Test
    fun defaultsToDisabledAndRightSide() {
        val config = OneHandedConfig()
        assertFalse(config.enabled)
        assertEquals(OneHandedSide.RIGHT, config.side)
    }

    @Test
    fun parsesStoredSideWithSafeFallback() {
        assertEquals(OneHandedSide.LEFT, OneHandedSide.fromStored("LEFT"))
        assertEquals(OneHandedSide.RIGHT, OneHandedSide.fromStored("RIGHT"))
        assertEquals(OneHandedSide.RIGHT, OneHandedSide.fromStored(null))
        assertEquals(OneHandedSide.RIGHT, OneHandedSide.fromStored("UNKNOWN"))
    }
}
