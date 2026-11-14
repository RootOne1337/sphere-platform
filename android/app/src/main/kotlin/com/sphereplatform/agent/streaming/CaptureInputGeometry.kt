package com.sphereplatform.agent.streaming

data class StreamPoint(val x: Int, val y: Int)

/** Captured once per session; all points of a gesture use the same geometry. */
internal data class CaptureInputGeometry(
    val sourceWidth: Int,
    val sourceHeight: Int,
    val frameWidth: Int,
    val frameHeight: Int,
    val sourceRotation: Int = 0,
) {
    init {
        require(listOf(sourceWidth, sourceHeight, frameWidth, frameHeight).all { it > 0 })
    }

    fun map(points: List<StreamPoint>, currentWidth: Int, currentHeight: Int, currentRotation: Int = 0): List<StreamPoint>? {
        // A rotated/resized display no longer matches the picture the operator saw.
        if (currentWidth != sourceWidth || currentHeight != sourceHeight || currentRotation != sourceRotation || points.isEmpty()) return null
        if (points.any { it.x !in 0 until frameWidth || it.y !in 0 until frameHeight }) return null
        return points.map {
            StreamPoint((it.x.toLong() * sourceWidth / frameWidth).toInt(),
                (it.y.toLong() * sourceHeight / frameHeight).toInt())
        }
    }
}
