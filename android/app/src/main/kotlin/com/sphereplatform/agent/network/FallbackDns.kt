package com.sphereplatform.agent.network

import okhttp3.Dns
import org.json.JSONObject
import timber.log.Timber
import java.io.ByteArrayOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.URL
import java.net.UnknownHostException
import javax.net.ssl.HttpsURLConnection

/**
 * DNS-резолвер с многоуровневым fallback для надёжной работы на эмуляторах.
 *
 * **Проблема:** На Android-эмуляторах (LDPlayer, Nox, MEmu) системный DNS
 * часто не резолвит внешние домены. Дополнительно, VirtualBox NAT в headless-режиме
 * блокирует UDP порт 53 — стандартные DNS-запросы не проходят.
 *
 * **Решение — 4-уровневый fallback:**
 * 1. Системный DNS (стандартное поведение OkHttp) — zero overhead при успехе
 * 2. DNS-over-HTTPS (DoH) через Cloudflare (1.1.1.1) и Google (8.8.8.8) —
 *    TCP-based, работает через любой NAT, не требует открытого UDP/53
 * 3. Raw UDP DNS к публичным резолверам (8.8.8.8, 1.1.1.1, 8.8.4.4) —
 *    RFC 1035, работает на эмуляторах с открытым UDP
 * 4. [UnknownHostException] — все резолверы исчерпаны
 *
 * **DoH использует [HttpsURLConnection] (НЕ OkHttp)** во избежание circular dependency:
 * OkHttp→FallbackDns→OkHttp. Подключение идёт по IP (1.1.1.1, 8.8.8.8) —
 * сами DoH-серверы не требуют DNS для доступа. TLS-сертификаты обоих провайдеров
 * содержат IP SAN (Subject Alternative Name) для своих IP-адресов.
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
        /** Таймаут DoH HTTP-запроса (мс) — на одну попытку, не суммарный. */
        private const val DOH_TIMEOUT_MS = 5_000
        /** Максимальный размер DoH JSON-ответа (защита от OOM). */
        private const val MAX_DOH_RESPONSE_CHARS = 16 * 1024  // 16KB
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

    /**
     * DoH-серверы (TCP, порт 443). Подключение по IP — DNS не нужен.
     * TLS-сертификаты содержат IP SAN для каждого адреса.
     *
     * Cloudflare: JSON API с Accept: application/dns-json
     * Google: JSON API (нативный формат /resolve)
     */
    private data class DohServer(val ip: String, val urlTemplate: String, val name: String)

    private val dohServers = listOf(
        DohServer("1.1.1.1", "https://1.1.1.1/dns-query?name=%s&type=A", "Cloudflare"),
        DohServer("1.0.0.1", "https://1.0.0.1/dns-query?name=%s&type=A", "Cloudflare-secondary"),
        DohServer("8.8.8.8", "https://8.8.8.8/resolve?name=%s&type=A", "Google"),
        DohServer("8.8.4.4", "https://8.8.4.4/resolve?name=%s&type=A", "Google-secondary"),
    )

    /** Публичные DNS-серверы для UDP fallback (порядок: Google → Cloudflare → Google secondary). */
    private val fallbackServers: List<InetAddress> = listOf(
        InetAddress.getByAddress(byteArrayOf(8, 8, 8, 8)),           // Google DNS
        InetAddress.getByAddress(byteArrayOf(1, 1, 1, 1)),           // Cloudflare DNS
        InetAddress.getByAddress(byteArrayOf(8, 8, 4, 4)),           // Google DNS secondary
    )

    /**
     * Резолвит hostname в список IP-адресов.
     *
     * Цепочка fallback:
     * 1. Системный DNS ([Dns.SYSTEM]) — zero overhead при успехе
     * 2. DNS-over-HTTPS (DoH) через Cloudflare/Google — TCP, работает через любой NAT
     * 3. Raw UDP DNS к публичным резолверам — для сред с открытым UDP/53
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
            Timber.d("FallbackDns: системный DNS не резолвит %s, пробую DoH", hostname)
        }

        // 2. DNS-over-HTTPS — TCP (порт 443), работает через VirtualBox NAT
        for (server in dohServers) {
            try {
                val result = resolveViaDoH(hostname, server)
                if (result.isNotEmpty()) {
                    Timber.i(
                        "FallbackDns: %s → %s (DoH через %s)",
                        hostname, result.first().hostAddress, server.name,
                    )
                    return result
                }
            } catch (e: Exception) {
                Timber.d("FallbackDns: DoH %s не удался: %s", server.name, e.message)
            }
        }

        // 3. Fallback: прямой UDP DNS-запрос к публичным резолверам
        for (server in fallbackServers) {
            try {
                val result = resolveViaUdp(hostname, server)
                if (result.isNotEmpty()) {
                    Timber.i(
                        "FallbackDns: %s → %s (UDP через %s)",
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

    // ── DNS-over-HTTPS (RFC 8484, JSON format) ─────────────────────────────

    /**
     * Резолвит hostname через DNS-over-HTTPS (DoH) к указанному серверу.
     *
     * Использует [HttpsURLConnection] (НЕ OkHttp) чтобы избежать circular dependency:
     * OkHttp → FallbackDns → OkHttp. Подключение по IP — DNS не нужен.
     *
     * @param hostname домен для запроса
     * @param server DoH-сервер (IP + URL-шаблон)
     * @return список A-записей (IPv4) или пустой список
     */
    private fun resolveViaDoH(hostname: String, server: DohServer): List<InetAddress> {
        val url = URL(String.format(server.urlTemplate, hostname))
        val conn = url.openConnection() as HttpsURLConnection
        try {
            conn.connectTimeout = DOH_TIMEOUT_MS
            conn.readTimeout = DOH_TIMEOUT_MS
            conn.requestMethod = "GET"
            conn.setRequestProperty("Accept", "application/dns-json")
            conn.useCaches = false

            if (conn.responseCode != 200) {
                Timber.d("FallbackDns: DoH %s → HTTP %d", server.name, conn.responseCode)
                return emptyList()
            }

            val body = conn.inputStream.bufferedReader(Charsets.UTF_8)
                .readText()
                .take(MAX_DOH_RESPONSE_CHARS)

            return parseDohJsonResponse(body)
        } finally {
            conn.disconnect()
        }
    }

    /**
     * Парсит JSON-ответ от DoH-сервера (формат Google/Cloudflare JSON API).
     *
     * Формат: {"Status":0, "Answer":[{"type":1, "data":"93.184.216.34", ...}]}
     *
     * @param body JSON-строка ответа
     * @return список IPv4-адресов из Answer-секции
     */
    private fun parseDohJsonResponse(body: String): List<InetAddress> {
        val json = JSONObject(body)
        // Status 0 = NOERROR (RFC 1035 §4.1.1)
        if (json.optInt("Status", -1) != 0) return emptyList()

        val answers = json.optJSONArray("Answer") ?: return emptyList()
        val addresses = mutableListOf<InetAddress>()

        for (i in 0 until answers.length()) {
            val answer = answers.getJSONObject(i)
            // Тип 1 = A-запись (IPv4)
            if (answer.optInt("type", 0) == DNS_TYPE_A) {
                val ip = answer.optString("data", "").takeIf { it.isNotBlank() } ?: continue
                runCatching {
                    addresses += InetAddress.getByName(ip)
                }.onFailure {
                    Timber.d("FallbackDns: невалидный IP в DoH ответе: %s", ip)
                }
            }
        }

        return addresses
    }

    // ── Raw UDP DNS (RFC 1035) ──────────────────────────────────────────────

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
