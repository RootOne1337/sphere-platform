package com.sphereplatform.agent.vpn

import android.util.AtomicFile
import com.sphereplatform.agent.commands.BoundedProcessRunner
import java.io.File
import java.util.Collections
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.Required
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

@Serializable
internal data class GuardUidRange(val first: Int, val last: Int)

/** App/sandbox/isolated UID space of primary user on the accepted API range.
 * System network services (0..9999) are NOT covered by this runtime guard.
 */
internal fun allAppUidRanges(ownerUid: Int): List<GuardUidRange> {
    require(ownerUid in 10000..19999)
    return listOfNotNull(
        if (ownerUid > 10000) GuardUidRange(10000, ownerUid - 1) else null,
        GuardUidRange(ownerUid + 1, 99999),
    )
}

@Serializable
internal data class UidGuardRecord(
    val operationId: String,
    val selectedUids: List<Int>,
    val ownerUid: Int,
    val phase: String,
    val interfaceName: String? = null,
    val interfaceIndex: Int? = null,
    val ipv6: String = "block",
    val allowRules: Boolean = phase in setOf("ALLOWING", "ALLOWED"),
    val lastMutation: String? = null,
    @Required val planVersion: Int = 4,
    val uidRanges: List<GuardUidRange> = emptyList(),
)

/** Only identifiers/state, never tunnel config or keys. One guard per APK. */
internal class UidGuardJournal(file: File) {
    private val atomic = AtomicFile(file)
    private val json = Json { ignoreUnknownKeys = false }
    fun read(): UidGuardRecord? {
        if (!atomic.baseFile.exists() && !File(atomic.baseFile.path + ".bak").exists()) return null
        return try {
            val bytes = atomic.openRead().use { it.readBytesLimited(16384) }
            json.decodeFromString<UidGuardRecord>(bytes.toString(Charsets.UTF_8)).also { UidGuardPlan.from(it) }
        } catch (_: Exception) { throw VpnPreparationException("vpn_guard_journal_unreadable") }
    }
    fun write(record: UidGuardRecord) {
        UidGuardPlan.from(record)
        atomic.baseFile.parentFile?.mkdirs()
        val output = atomic.startWrite()
        try { output.write(json.encodeToString(record).toByteArray()); atomic.finishWrite(output) }
        catch (failure: Exception) { atomic.failWrite(output); throw failure }
    }
    private fun java.io.InputStream.readBytesLimited(limit: Int): ByteArray {
        val result = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(1024)
        while (true) {
            val n = read(buffer)
            if (n < 0) return result.toByteArray()
            if (result.size() + n > limit) throw IllegalArgumentException()
            result.write(buffer, 0, n)
        }
    }
}

/** Private UID-only FILTER chains and a fresh UID routing table.
 * The table keeps an unreachable default after the TUN route disappears. Kernel
 * routes bind to interface indices, so a reused tun0 name cannot inherit access.
 * No global default policy, main-table route, FORWARD or NAT is changed.
 */
internal class UidGuardPlan private constructor(val record: UidGuardRecord, val chain: String, val mark: Long, val table: Int) {
    private val families = listOf("iptables", "ip6tables")
    private val mangle = chain.replace("SPV2F_", "SPV2M_")
    private val priority = 9000 + table % 1000
    // Version 3 is retained only to verify/release its exact persisted rules.
    // Even nominally unused fwmark bits break egress on some Android kernels.
    private val legacyMarks = record.planVersion == 3
    private val ranges = if (record.planVersion == 5) record.uidRanges else record.selectedUids.map { GuardUidRange(it, it) }
    private fun routeUid(range: GuardUidRange) = "${range.first}-${range.last}"
    private fun ownerUid(range: GuardUidRange) = if (range.first == range.last) "${range.first}" else routeUid(range)
    private fun legacy(lines: List<String>) = if (legacyMarks) lines else emptyList()
    private fun allowRule(name: String) = "-o $name" + (if (legacyMarks) " -m mark --mark $mark/0x1fe00000" else "") + " -j RETURN"
    private fun command(tool: String, args: String, tableName: String = "filter") = "$tool -w 2 -t $tableName $args"
    private fun ip(tool: String) = if (tool == "iptables") "ip -4" else "ip -6"
    private fun marker() = "SPHERE_UID_GUARD_${record.operationId}_${record.phase}"
    private fun script(lines: List<String>) = (listOf("set -eu") + lines + "printf '%s\\n' '${marker()}'").joinToString("\n")
    fun expectedMarker() = marker()

    fun block(): String {
        require(!legacyMarks) { "vpn_legacy_guard_cleanup_only" }
        return script(families.flatMap { tool -> listOf(
            "routes=$(${ip(tool)} route show table $table)",
            "test -z \"\$routes\"",
            "rules=$(${ip(tool)} rule show)",
            "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- 'lookup $table' || :)\" = '0'",
        ) } + families.flatMap { tool ->
            listOf("${ip(tool)} route add blackhole default table $table metric 32760") +
                ranges.map { "${ip(tool)} rule add pref $priority uidrange ${routeUid(it)} lookup $table" } +
                listOf(command(tool, "-N $chain"), command(tool, "-A $chain -j DROP")) +
                ranges.map { command(tool, "-I OUTPUT 1 -m owner --uid-owner ${ownerUid(it)} -j $chain") }
        } + proof(allowed = false))
    }

    fun allow(): String {
        require(!legacyMarks) { "vpn_legacy_guard_cleanup_only" }
        require(record.phase == "ALLOWING")
        val name = record.interfaceName!!
        val index = record.interfaceIndex!!
        return script(proof(allowed = false) + listOf(
            "test \"$(cat /sys/class/net/$name/ifindex)\" = '$index'",
        ) + families.flatMap { tool ->
            if (tool == "ip6tables" && record.ipv6 == "block") emptyList() else listOf(
                "${ip(tool)} route add default dev $name table $table metric 10",
                "test \"$(cat /sys/class/net/$name/ifindex)\" = '$index'",
                command(tool, "-I $chain 1 ${allowRule(name)}"))
        } + proof(allowed = true) + linkProof())
    }

    fun verify(allowed: Boolean): String = script(proof(allowed) + if (allowed) linkProof() else emptyList())

    fun pause(): String {
        require(!legacyMarks) { "vpn_legacy_guard_cleanup_only" }
        require(record.phase == "BLOCKING" && record.allowRules)
        val name = record.interfaceName!!
        val index = record.interfaceIndex!!
        val wasClosed = "! test -e /sys/class/net/$name/ifindex || test \"$(cat /sys/class/net/$name/ifindex)\" != '$index'"
        val validation = listOf("if $wasClosed; then") + proof(allowed = true, closed = true) +
            listOf("else") + proof(allowed = true) + listOf("fi")
        val changes = families.flatMap { tool ->
            if (tool == "ip6tables" && record.ipv6 == "block") emptyList() else listOf(
                command(tool, "-D $chain ${allowRule(name)}"),
                "routes=$(${ip(tool)} route show table $table)",
                "if test \"$(printf '%s\\n' \"\$routes\" | grep -c .)\" = '2'; then",
                "test \"$(cat /sys/class/net/$name/ifindex)\" = '$index'",
                "${ip(tool)} route del default dev $name table $table metric 10", "fi")
        }
        return script(validation + changes + proof(allowed = false))
    }

    private fun linkProof(): List<String> {
        require(record.interfaceName != null && record.interfaceIndex != null)
        return listOf("test \"$(cat /sys/class/net/${record.interfaceName}/ifindex)\" = '${record.interfaceIndex}'")
    }

    fun release(): String {
        require(record.phase == "RELEASING")
        val closedCheck = if (record.interfaceName == null) emptyList() else listOf(
            // Reused interface with a different index is not our still-open TUN.
            "if test -e /sys/class/net/${record.interfaceName}/ifindex; then test \"$(cat /sys/class/net/${record.interfaceName}/ifindex)\" != '${record.interfaceIndex}'; fi",
        )
        return script(closedCheck + proof(allowed = record.allowRules, closed = true) + families.flatMap { tool ->
            ranges.flatMap { listOf(command(tool, "-D OUTPUT -m owner --uid-owner ${ownerUid(it)} -j $chain")) +
                legacy(listOf(command(tool, "-D OUTPUT -m owner --uid-owner ${ownerUid(it)} -j $mangle", "mangle"))) } +
                listOf(command(tool, "-F $chain"), command(tool, "-X $chain")) +
                legacy(listOf(command(tool, "-F $mangle", "mangle"), command(tool, "-X $mangle", "mangle"))) +
                ranges.map { "${ip(tool)} rule del pref $priority uidrange ${routeUid(it)} lookup $table" } + listOf(
                    "${ip(tool)} route del blackhole default table $table metric 32760",
                    // Successful listing also proves the table is readable.
                    "rules=$(${command(tool, "-S OUTPUT")})",
                    "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- '-j $chain' || :)\" = '0'",
                ) + legacy(listOf("rules=$(${command(tool, "-S OUTPUT", "mangle")})",
                    "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- '-j $mangle' || :)\" = '0'")) + listOf(
                    "rules=$(${ip(tool)} rule show)",
                    "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- 'lookup $table' || :)\" = '0'",
                    "routes=$(${ip(tool)} route show table $table)", "test -z \"\$routes\"")
        })
    }

    private fun proof(allowed: Boolean, closed: Boolean = false): List<String> = families.flatMap { tool ->
        val familyAllowed = allowed && (tool == "iptables" || record.ipv6 == "tunnel")
        listOf(command(tool, "-C $chain -j DROP")) + legacy(listOf(
            command(tool, "-C $mangle -j MARK --set-xmark $mark/0x1fe00000", "mangle"),
            command(tool, "-C $mangle -j ACCEPT", "mangle"))) + listOf(
            "routes=$(${ip(tool)} route show table $table)",
            "test \"$(printf '%s\\n' \"\$routes\" | grep -c -- '^blackhole default.*metric 32760')\" = '1'",
            "test \"$(printf '%s\\n' \"\$routes\" | grep -c .)\" = '${if (familyAllowed && !closed) 2 else 1}'",
        ) + (if (familyAllowed && !closed) listOf(
            "test \"$(printf '%s\\n' \"\$routes\" | grep -Ec -- '^default dev ${record.interfaceName}([[:space:]].*)? metric 10([[:space:]]|$)')\" = '1'",
        ) else emptyList()) + listOf(
            "rules=$(${ip(tool)} rule show)",
            "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- 'lookup $table')\" = '${ranges.size}'") +
            ranges.map { "test \"$(printf '%s\\n' \"\$rules\" | grep -Ec -- '^$priority:.*uidrange ${routeUid(it)} .*lookup $table([[:space:]]|$)')\" = '1'" } +
            ranges.flatMap { listOf(command(tool, "-C OUTPUT -m owner --uid-owner ${ownerUid(it)} -j $chain")) +
                legacy(listOf(command(tool, "-C OUTPUT -m owner --uid-owner ${ownerUid(it)} -j $mangle", "mangle"))) } +
            listOf(
                "rules=$(${command(tool, "-S $chain")})",
                "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- '^-A $chain ')\" = '${if (familyAllowed) 2 else 1}'",
                "test \"$(printf '%s\\n' \"\$rules\" | tail -n 1)\" = '-A $chain -j DROP'",
                "rules=$(${command(tool, "-S OUTPUT")})",
                "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- '-j $chain')\" = '${ranges.size}'",
            ) + legacy(listOf("rules=$(${command(tool, "-S $mangle", "mangle")})",
                "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- '^-A $mangle ')\" = '2'",
                "test \"$(printf '%s\\n' \"\$rules\" | tail -n 1)\" = '-A $mangle -j ACCEPT'",
                "rules=$(${command(tool, "-S OUTPUT", "mangle")})",
                "test \"$(printf '%s\\n' \"\$rules\" | grep -c -- '-j $mangle')\" = '${ranges.size}'",
            )) + if (familyAllowed) listOf(command(tool, "-C $chain ${allowRule(record.interfaceName!!)}")) else emptyList()
    }

    companion object {
        fun from(record: UidGuardRecord): UidGuardPlan {
            require(record.planVersion in setOf(3, 4, 5))
            val id = UUID.fromString(record.operationId)
            require(id.toString() == record.operationId)
            require(record.ownerUid >= 10000)
            if (record.planVersion == 5) {
                require(record.selectedUids.isEmpty() && record.uidRanges == allAppUidRanges(record.ownerUid))
            } else {
                require(record.uidRanges.isEmpty())
                require(record.selectedUids.size in 1..64 && record.selectedUids.toSet().size == record.selectedUids.size)
            }
            require(record.selectedUids.all { it > 0 && it % 100000 >= 10000 && it != record.ownerUid })
            require(record.phase in setOf("INTENT", "BLOCKED", "ALLOWING", "ALLOWED", "BLOCKING", "RELEASING", "RELEASED", "UNKNOWN"))
            require(record.lastMutation == null || record.lastMutation in setOf("INTENT", "ALLOWING", "BLOCKING", "RELEASING"))
            require(record.ipv6 in setOf("block", "tunnel"))
            require((record.interfaceName == null) == (record.interfaceIndex == null))
            if (record.interfaceName != null) {
                require(Regex("tun[0-9]{1,4}").matches(record.interfaceName) && record.interfaceIndex!! > 0)
            }
            require(record.phase !in setOf("ALLOWING", "ALLOWED", "BLOCKING") || record.interfaceName != null)
            require(record.phase !in setOf("ALLOWING", "ALLOWED", "BLOCKING") || record.allowRules)
            // Preserve the exact version 3 mark for explicit cleanup only.
            // Version 4 never reads, writes or installs any fwmark rules.
            val mark = ((id.leastSignificantBits and 0xff).coerceAtLeast(1)) shl 21
            val table = 2000000 + ((id.mostSignificantBits xor id.leastSignificantBits) and 0xfffff).toInt()
            return UidGuardPlan(record.copy(selectedUids = Collections.unmodifiableList(record.selectedUids.toList()),
                uidRanges = Collections.unmodifiableList(record.uidRanges.toList())), "SPV2F_" + id.toString().replace("-", "").take(20), mark, table)
        }
    }
}

internal fun interface GuardRootExecutor { suspend fun execute(script: String, expectedMarker: String) }

internal class BoundedGuardRootExecutor(private val privateDirectory: File, private val diagnosticResult: ((Int, String, String) -> Unit)? = null) : GuardRootExecutor {
    private val runner = BoundedProcessRunner()
    override suspend fun execute(script: String, expectedMarker: String) {
        // Some emulator su daemons cap a single argument at 4 KiB. The complete
        // verified plan can exceed that; run a short argv against an owned file.
        // Callers supply an application-private filesDir subdirectory, never /tmp.
        if (script.toByteArray(Charsets.UTF_8).size > 262144) throw VpnPreparationException("vpn_guard_script_bounds")
        val directory = privateDirectory.canonicalFile
        if ((!directory.isDirectory && !directory.mkdirs()) || !directory.setReadable(false, false)
            || !directory.setWritable(false, false) || !directory.setExecutable(false, false)
            || !directory.setReadable(true, true) || !directory.setWritable(true, true) || !directory.setExecutable(true, true)) {
            throw VpnPreparationException("vpn_guard_private_directory_unavailable")
        }
        val file = File(directory, "guard-${UUID.randomUUID()}.sh")
        if (!file.createNewFile()) throw VpnPreparationException("vpn_guard_script_unavailable")
        try {
            if (!file.setReadable(false, false) || !file.setWritable(false, false)
                || !file.setReadable(true, true) || !file.setWritable(true, true)) throw VpnPreparationException("vpn_guard_script_permissions")
            java.io.FileOutputStream(file).use { it.write(script.toByteArray(Charsets.UTF_8)); it.fd.sync() }
            val path = "'" + file.path.replace("'", "'\\''") + "'"
            val result = runner.run({ Runtime.getRuntime().exec(arrayOf("su", "-c", "sh $path")) }, 15000, 16384, 4096)
            diagnosticResult?.invoke(result.exitCode, result.stdout.bytes.toString(Charsets.UTF_8), result.stderr.bytes.toString(Charsets.UTF_8))
            if (result.exitCode != 0 || result.stdout.truncated || result.stderr.truncated
                || result.stdout.bytes.toString(Charsets.UTF_8).lineSequence().count { it.trimEnd('\r') == expectedMarker } != 1) {
                throw VpnPreparationException("vpn_guard_kernel_not_confirmed")
            }
        } finally {
            // Metadata only, but a stale executable plan must never be reused.
            file.delete()
        }
    }
}

/** A failed/timeout mutation is durable UNKNOWN, never automatically cleared.
 * This is the device guard journal, not the server's apply/rotate operation log.
 */
internal class SelectedUidGuard(private val journal: UidGuardJournal, private val root: GuardRootExecutor) {
    private val lock = Mutex()
    suspend fun block(operation: UUID, apps: ResolvedAppSelection, ownerUid: Int): UidGuardRecord = lock.withLock {
        val previous = journal.read()
        if (previous?.phase?.let { it != "RELEASED" } == true) throw VpnPreparationException("vpn_guard_reconciliation_required")
        if (previous?.operationId == operation.toString()) throw VpnPreparationException("vpn_guard_operation_id_reused")
        require(apps.mode in setOf("selected_apps", "all_apps_except_control"))
        val broad = apps.mode == "all_apps_except_control"
        val intent = UidGuardRecord(operation.toString(), apps.uids.sorted(), ownerUid, "INTENT", ipv6 = apps.ipv6,
            planVersion = if (broad) 5 else 4, uidRanges = if (broad) allAppUidRanges(ownerUid) else emptyList())
        mutate(intent, "BLOCKED") { it.block() }
    }
    suspend fun allow(operation: UUID, interfaceName: String, index: Int): UidGuardRecord = lock.withLock {
        val previous = owned(operation, "BLOCKED")
        mutate(previous.copy(phase = "ALLOWING", interfaceName = interfaceName, interfaceIndex = index, allowRules = true), "ALLOWED") { it.allow() }
    }
    suspend fun pause(operation: UUID): UidGuardRecord = lock.withLock {
        mutate(owned(operation, "ALLOWED").copy(phase = "BLOCKING"), "BLOCKED") { it.pause() }
    }
    suspend fun release(operation: UUID): UidGuardRecord = lock.withLock {
        val previous = journal.read() ?: throw VpnPreparationException("vpn_guard_not_found")
        if (previous.operationId != operation.toString() || previous.phase !in setOf("BLOCKED", "ALLOWED")) throw VpnPreparationException("vpn_guard_reconciliation_required")
        mutate(previous.copy(phase = "RELEASING"), "RELEASED") { it.release() }
    }
    private fun owned(operation: UUID, phase: String): UidGuardRecord {
        val record = journal.read() ?: throw VpnPreparationException("vpn_guard_not_found")
        if (record.operationId != operation.toString() || record.phase != phase) throw VpnPreparationException("vpn_guard_reconciliation_required")
        return record
    }
    private suspend fun mutate(intent: UidGuardRecord, completed: String, script: (UidGuardPlan) -> String): UidGuardRecord {
        val pending = intent.copy(lastMutation = intent.phase)
        val plan = UidGuardPlan.from(pending)
        val command = script(plan) // Validate all inputs before durable intent/kernel writes.
        journal.write(pending)
        try {
            root.execute(command, plan.expectedMarker())
            return pending.copy(phase = completed, allowRules = completed == "ALLOWED").also(journal::write)
        } catch (failure: Exception) {
            runCatching { journal.write(pending.copy(phase = "UNKNOWN")) }
            if (failure is CancellationException) throw failure
            throw VpnPreparationException("vpn_guard_outcome_unknown")
        }
    }
}
