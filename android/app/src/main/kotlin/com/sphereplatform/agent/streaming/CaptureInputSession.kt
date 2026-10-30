package com.sphereplatform.agent.streaming

import java.util.UUID

/** One capture identity, including same-size restarts and 180-degree rotations. */
data class CaptureInputSession(
    val epoch: String,
    val physicalWidth: Int,
    val physicalHeight: Int,
    val frameWidth: Int,
    val frameHeight: Int,
    val rotation: Int,
) {
    init {
        require(epoch.matches(Regex("[A-Za-z0-9_-]{8,128}")))
        require(listOf(physicalWidth, physicalHeight, frameWidth, frameHeight).all { it in 1..16384 })
        require(rotation in 0..3)
    }

    fun matchesDisplay(width: Int, height: Int, rotation: Int): Boolean =
        physicalWidth == width && physicalHeight == height && this.rotation == rotation

    fun map(epoch: String, width: Int, height: Int, point: StreamPoint): StreamPoint? {
        if (this.epoch != epoch || frameWidth != width || frameHeight != height) return null
        return CaptureInputGeometry(physicalWidth, physicalHeight, frameWidth, frameHeight, rotation)
            .map(listOf(point), physicalWidth, physicalHeight, rotation)?.singleOrNull()
    }

    companion object {
        internal fun create(geometry: CaptureInputGeometry): CaptureInputSession = CaptureInputSession(
            UUID.randomUUID().toString(), geometry.sourceWidth, geometry.sourceHeight,
            geometry.frameWidth, geometry.frameHeight, geometry.sourceRotation,
        )
    }
}
