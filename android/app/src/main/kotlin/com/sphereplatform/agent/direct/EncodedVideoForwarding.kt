package com.sphereplatform.agent.direct

import com.sphereplatform.agent.streaming.EncodedCaptureFrame
import java.util.concurrent.atomic.AtomicBoolean

/** Bounds Java-owned coded data, including frames retained by the native pipeline. */
class EncodedVideoBudget {
    companion object { const val MAX_FRAMES = 3; const val MAX_BYTES = 2 * 1024 * 1024; const val MAX_FRAME_BYTES = 1024 * 1024 }
    private var frames = 0
    private var bytes = 0
    private var closed = false
    @Synchronized fun reserve(size: Int): (() -> Unit)? {
        if (closed || size !in 1..MAX_FRAME_BYTES || frames >= MAX_FRAMES || bytes + size > MAX_BYTES) return null
        frames++; bytes += size
        val released = AtomicBoolean(false)
        return { if (released.compareAndSet(false, true)) synchronized(this) { frames--; bytes -= size } }
    }
    @Synchronized fun close() { closed = true }
    @Synchronized fun retained() = frames to bytes
}

/** Never forward a delta picture across a local drop, reordering or encoder reset. */
class EncodedVideoOrder {
    private var sequence = 0L
    private var timestamp = 0L
    private var waitingKey = true
    @Synchronized fun admit(next: Long, timeNs: Long, key: Boolean): Boolean {
        if (next <= sequence || timeNs <= timestamp) { waitingKey = true; return false }
        if (sequence != 0L && next != sequence + 1) waitingKey = true
        sequence = next; timestamp = timeNs
        if (key) waitingKey = false
        return !waitingKey
    }
    @Synchronized fun invalidate() { waitingKey = true }
}

/** Annex-B input only. Prefix the encoder's current SPS/PPS on each IDR for RTP join/recovery. */
object EncodedVideoAccessUnit {
    private fun types(bytes: ByteArray): List<Pair<Int, Int>>? {
        if (bytes.isEmpty() || bytes.size > EncodedVideoBudget.MAX_FRAME_BYTES) return null
        val starts = mutableListOf<Pair<Int, Int>>()
        var i = 0
        while (i + 3 < bytes.size) {
            val prefix = if (bytes[i] == 0.toByte() && bytes[i + 1] == 0.toByte()) when {
                bytes[i + 2] == 1.toByte() -> 3
                i + 4 < bytes.size && bytes[i + 2] == 0.toByte() && bytes[i + 3] == 1.toByte() -> 4
                else -> 0
            } else 0
            if (prefix != 0) {
                if (starts.size >= 64) return null
                starts.add(i to prefix); i += prefix
            } else i++
        }
        if (starts.firstOrNull()?.first != 0) return null
        return starts.map { (offset, prefix) ->
            if (offset + prefix >= bytes.size || bytes[offset + prefix].toInt() and 0x80 != 0) return null
            offset + prefix to (bytes[offset + prefix].toInt() and 31)
        }
    }

    fun prepare(frame: EncodedCaptureFrame): ByteArray? {
        val nals = types(frame.data) ?: return null
        if (nals.any { it.second !in setOf(1, 5, 6, 7, 8, 9) } ||
            nals.none { it.second in setOf(1, 5) } || frame.keyFrame != nals.any { it.second == 5 }) return null
        if (!frame.keyFrame) return frame.data
        val sps = frame.sps ?: return null
        val pps = frame.pps ?: return null
        if (sps.size > 4096 || pps.size > 4096) return null
        val spsNals = types(sps) ?: return null
        if (spsNals.size != 1 || spsNals[0].second != 7 || types(pps)?.map { it.second } != listOf(8)) return null
        val at = spsNals[0].first
        // The advertised constrained-baseline H.264 level 3.1 must match the actual SPS.
        if (at + 3 >= sps.size || sps[at + 1].toInt() and 255 != 66 ||
            sps[at + 2].toInt() and 0x40 == 0 || sps[at + 3].toInt() and 255 !in 1..31) return null
        if (sps.size + pps.size + frame.data.size > EncodedVideoBudget.MAX_FRAME_BYTES) return null
        return sps + pps + frame.data
    }
}
