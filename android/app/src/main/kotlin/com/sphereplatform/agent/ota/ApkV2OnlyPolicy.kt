package com.sphereplatform.agent.ota

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * A conservative format gate for an OEM's legacy signature API, NOT a signature
 * verifier. PackageManager obtains certificates and the OS installer verifies
 * the APK. V3/rotation, unknown blocks, ZIP64 and malformed files fail closed.
 */
internal object ApkV2OnlyPolicy {
    private const val V2 = 0x7109871a
    private const val PADDING = 0x42726577
    private const val MAX_BLOCK_BYTES = 2 * 1024 * 1024

    fun allows(file: File): Boolean {
        return try {
            RandomAccessFile(file, "r").use { input ->
                val length = input.length()
                if (length < 46) return false
                val tailSize = minOf(length, 65_557L).toInt()
                val tail = ByteArray(tailSize)
                input.seek(length - tailSize)
                input.readFully(tail)
                val zip = ByteBuffer.wrap(tail).order(ByteOrder.LITTLE_ENDIAN)
                val eocd = (tailSize - 22 downTo 0).firstOrNull { offset ->
                    zip.getInt(offset) == 0x06054b50 &&
                        offset + 22 + (zip.getShort(offset + 20).toInt() and 0xffff) == tailSize
                } ?: return false
                if (zip.getShort(eocd + 4).toInt() != 0 || zip.getShort(eocd + 6).toInt() != 0) return false
                val entries = zip.getShort(eocd + 10).toInt() and 0xffff
                if (entries == 0 || entries == 0xffff || (zip.getShort(eocd + 8).toInt() and 0xffff) != entries) return false
                val directorySize = zip.getInt(eocd + 12).toLong() and 0xffffffffL
                val directory = zip.getInt(eocd + 16).toLong() and 0xffffffffL
                val eocdAbsolute = length - tailSize + eocd
                if (directory < 32 || directorySize == 0xffffffffL || directory == 0xffffffffL ||
                    directorySize < 46 || directory + directorySize != eocdAbsolute) return false
                input.seek(directory)
                val signature = ByteArray(4)
                input.readFully(signature)
                if (ByteBuffer.wrap(signature).order(ByteOrder.LITTLE_ENDIAN).int != 0x02014b50) return false
                val footer = ByteArray(24)
                input.seek(directory - 24)
                input.readFully(footer)
                if (!footer.copyOfRange(8, 24).contentEquals("APK Sig Block 42".toByteArray(Charsets.US_ASCII))) return false
                val size = ByteBuffer.wrap(footer).order(ByteOrder.LITTLE_ENDIAN).long
                if (size < 36 || size > MAX_BLOCK_BYTES || size + 8 > directory) return false
                val block = ByteArray((size + 8).toInt())
                input.seek(directory - size - 8)
                input.readFully(block)
                val buffer = ByteBuffer.wrap(block).order(ByteOrder.LITTLE_ENDIAN)
                if (buffer.long != size) return false
                val end = block.size - 24
                var sawV2 = false
                var sawPadding = false
                while (buffer.position() < end) {
                    if (end - buffer.position() < 12) return false
                    val pairSize = buffer.long
                    if (pairSize < 4 || pairSize > end - buffer.position()) return false
                    when (buffer.int) {
                        V2 -> {
                            if (sawV2 || pairSize == 4L) return false
                            sawV2 = true
                        }
                        PADDING -> {
                            if (sawPadding) return false
                            sawPadding = true
                        }
                        else -> return false
                    }
                    buffer.position(buffer.position() + (pairSize - 4).toInt())
                }
                sawV2 && buffer.position() == end
            }
        } catch (_: Exception) {
            false
        }
    }
}
