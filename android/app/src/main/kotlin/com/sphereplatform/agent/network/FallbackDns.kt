package com.sphereplatform.agent.network

import okhttp3.Dns
import timber.log.Timber
import java.io.ByteArrayOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.UnknownHostException

/**
 * DNS-резолвер с fallback на публичные DNS-серверы (Google, Cloudflare).
 *
 * **Проблема:** На Android-эмуляторах (LDPlayer, Nox, MEmu) системный DNS
 * часто не резолвит внешние домены — особенно на свежих инстансах. Это блокирует
 * auto-provision и WebSocket-подключение на чистых установках APK.
 *
 * **Решение:** Сначала пробуем системный DNS (стандартное поведение OkHttp).
 * При неудаче ([UnknownHostException]) отправляем raw UDP DNS A-запрос (RFC 1035)
 * напрямую к Google DNS (8.8.8.8), Cloudflare DNS (1.1.1.1) и Google secondary (8.8.4.4).
 *
 * **Для устройств с работающим DNS:** Никаких изменений — fallback не вызывается,
 * overhead = 0. Обратная совместимость полная.
 *
 * @see okhttp3.Dns
 */
class FallbackDns : Dns {

    companion object {
        /** Таймаут UDP-запроса к публичному DNS (мс). */
        private const val UDP_TIMEOUT_MS = 3_000
        /** DNS-порт (RFC 1035). */
        private const val DNS_PORT = 53
        /** Максимальный размер DNS UDP-ответа (RFC 1035 §2.3.4). */
        private const val MAX_UDP_RESPONSE = 512
        /** DNS A-запись = тип 1 (RFC 1035 §3.2.2). */
        private const val DNS_TYPE_A = 1
        /** Длина IPv4-адреса в байтах. */
        private const val IPV4_LENGTH = 4
        /** Маска для определения compression pointer (RFC 1035 §4.1.4). */
        private const val COMPRESSION_MASK = 0xC0
    }

    /** Публичные DNS-серверы для fallback (порядок: Google → Cloudflare → Google secondary). */
    private val fallbackServers: List<InetAddress> = listOf(
        InetAddress.getByAddress(byteArrayOf(8, 8, 8, 8)),           // Google DNS
        InetAddress.getByAddress(byteArrayOf(1, 1, 1, 1)),           // Cloudflare DNS
        InetAddress.getByAddress(byteArrayOf(8, 8, 4, 4)),           // Google DNS secondary
    )

    /**
     * Резолвит hostname в список IP-адресов.
     *
     * 1. Пробует системный DNS ([Dns.SYSTEM]).
     * 2. При [UnknownHostException] — пробует UDP-запрос к публичным DNS.
     *
     * @param hostname домен для резолвинга (например, "sphere.serveousercontent.com")
     * @return список [InetAddress] (минимум один)
     * @throws UnknownHostException если все резолверы не смогли разрезолвить домен
     */
    override fun lookup(hostname: String): List<InetAddress> {
        // 1. Системный DNS — стандартное поведение, zero overhead при успехе
        try {
            val result = Dns.SYSTEM.lookup(hostname)
            if (result.isNotEmpty()) return result
        } catch (_: UnknownHostException) {
            Timber.d("FallbackDns: системный DNS не резолвит %s, пробую публичные DNS", hostname)
        }

        // 2. Fallback: прямой UDP DNS-запрос к публичным резолверам
        for (server in fallbackServers) {
            try {
                val result = resolveViaUdp(hostname, server)
                if (result.isNotEmpty()) {
                    Timber.i(
                        "FallbackDns: %s → %s (через %s)",
                        hostname, result.first().hostAddress, server.hostAddress,
                    )
                    return result
                }
            } catch (e: Exception) {
                Timber.d("FallbackDns: UDP к %s не удался: %s", server.hostAddress, e.message)
            }
        }

        throw UnknownHostException("FallbackDns: не удалось разрезолвить $hostname")
    }

    /**
     * Отправляет raw UDP DNS A-запрос к указанному DNS-серверу (RFC 1035).
     *
     * @param hostname домен для запроса
     * @param dnsServer IP-адрес DNS-сервера
     * @return список A-записей (IPv4) или пустой список
     */
    private fun resolveViaUdp(hostname: String, dnsServer: InetAddress): List<InetAddress> {
        val query = buildDnsQuery(hostname)
        DatagramSocket().use { socket ->
            socket.soTimeout = UDP_TIMEOUT_MS
            socket.send(DatagramPacket(query, query.size, dnsServer, DNS_PORT))
            val buf = ByteArray(MAX_UDP_RESPONSE)
            val recv = DatagramPacket(buf, buf.size)
            socket.receive(recv)
            return parseDnsResponse(buf, recv.length)
        }
    }

    // ── DNS wire format (RFC 1035) ──────────────────────────────────────────

    /**
     * Строит DNS A-запрос в wire-формате.
     * Header(12 байт) + Question(QNAME + QTYPE=A + QCLASS=IN).
     */
    private fun buildDnsQuery(hostname: String): ByteArray {
        val out = ByteArrayOutputStream(64)
        // Header — Transaction ID, Flags(RD=1), QDCOUNT=1
        out.write(0xAB); out.write(0xCD)
        out.write(0x01); out.write(0x00)
        out.write(0x00); out.write(0x01) // QDCOUNT = 1
        out.write(0x00); out.write(0x00) // ANCOUNT = 0
        out.write(0x00); out.write(0x00) // NSCOUNT = 0
        out.write(0x00); out.write(0x00) // ARCOUNT = 0
        // QNAME: length-prefixed labels
        for (label in hostname.split(".")) {
            out.write(label.length)
            out.write(label.toByteArray(Charsets.US_ASCII))
        }
        out.write(0x00) // Конец QNAME
        // QTYPE = A (1), QCLASS = IN (1)
        out.write(0x00); out.write(0x01)
        out.write(0x00); out.write(0x01)
        return out.toByteArray()
    }

    /**
     * Парсит DNS-ответ, извлекая A-записи (IPv4 адреса) из Answer-секции.
     */
    private fun parseDnsResponse(data: ByteArray, length: Int): List<InetAddress> {
        if (length < 12) return emptyList()

        val answerCount = (data[6].ui() shl 8) or data[7].ui()
        if (answerCount == 0) return emptyList()

        // Пропускаем Header(12) + Question-секцию
        var pos = 12
        val questionCount = (data[4].ui() shl 8) or data[5].ui()
        repeat(questionCount) {
            pos = skipDnsName(data, pos, length)
            pos += 4 // QTYPE(2) + QCLASS(2)
        }

        // Парсим Answer RR
        val addresses = mutableListOf<InetAddress>()
        repeat(answerCount) {
            if (pos >= length) return@repeat
            pos = skipDnsName(data, pos, length)
            if (pos + 10 > length) return@repeat
            val type = (data[pos].ui() shl 8) or data[pos + 1].ui()
            val rdLength = (data[pos + 8].ui() shl 8) or data[pos + 9].ui()
            pos += 10 // TYPE(2) + CLASS(2) + TTL(4) + RDLENGTH(2)
            if (type == DNS_TYPE_A && rdLength == IPV4_LENGTH && pos + IPV4_LENGTH <= length) {
                addresses += InetAddress.getByAddress(data.copyOfRange(pos, pos + IPV4_LENGTH))
            }
            pos += rdLength
        }
        return addresses
    }

    /** Пропускает DNS name (inline labels + compression pointers, RFC 1035 §4.1.4). */
    private fun skipDnsName(data: ByteArray, start: Int, length: Int): Int {
        var pos = start
        while (pos < length) {
            val b = data[pos].ui()
            if (b == 0) { pos += 1; break }
            if ((b and COMPRESSION_MASK) == COMPRESSION_MASK) { pos += 2; break }
            pos += 1 + b
        }
        return pos
    }

    /** Byte → unsigned Int (0..255). */
    private fun Byte.ui(): Int = toInt() and 0xFF
}
