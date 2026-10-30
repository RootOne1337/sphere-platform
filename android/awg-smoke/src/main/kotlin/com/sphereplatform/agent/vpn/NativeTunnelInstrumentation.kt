package com.sphereplatform.agent.vpn

import android.app.Activity
import android.app.Instrumentation
import android.net.LocalSocket
import android.net.LocalSocketAddress
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.os.Process
import android.system.Os
import com.sphereplatform.agent.commands.BoundedProcessRunner
import java.io.File
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Debug-only fixture. No VpnService/Android default network is configured. */
class NativeTunnelInstrumentation : Instrumentation() {
    private var arguments = Bundle()
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); this.arguments = arguments ?: Bundle(); start() }
    override fun onStart() = runBlocking {
        val context = targetContext
        val status = File(context.filesDir, "native-session-status.json")
        val id = UUID.fromString(arguments.getString("operationId"))
        val directRoot = BoundedGuardRootExecutor(File(context.filesDir, "guard-scripts")) { code, out, err ->
            File(context.filesDir, "guard-execution.json").writeText(buildJsonObject {
                put("exitCode", code); put("stdout", out); put("stderr", err)
            }.toString())
        }
        // Remote diagnostic apps need not be granted superuser. In this mode the
        // operator executes the exact fixture plan via Sphere's already-authorized
        // root session, then acknowledges its checked marker. Never used by app/.
        val broker = arguments.getString("rootBroker") == "sphere"
        val rootExecutor = if (!broker) directRoot else GuardRootExecutor { script, marker ->
            val nonce = UUID.randomUUID().toString()
            val plan = File(context.filesDir, "broker-$nonce.sh")
            val ack = File(context.filesDir, "broker-$nonce.ack")
            val request = File(context.filesDir, "broker-request.json")
            plan.writeText(script)
            request.writeText(buildJsonObject { put("operationId", id.toString()); put("nonce", nonce); put("script", plan.path); put("marker", marker) }.toString())
            try {
                repeat(200) { if (!ack.exists()) delay(100) }
                if (!ack.exists()) throw VpnPreparationException("fixture_root_broker_unconfirmed")
            } finally { request.delete(); plan.delete(); ack.delete() }
        }
        val guard = SelectedUidGuard(UidGuardJournal(File(context.filesDir, "guard.json")), rootExecutor)
        fun publish(phase: String, handshake: Long = 0, reason: String? = null) {
            status.writeText(buildJsonObject {
                put("operationId", id.toString()); put("phase", phase); put("handshakeEpochSeconds", handshake)
                put("reason", reason); put("ownerUid", Process.myUid())
            }.toString())
        }
        try {
            if (arguments.getString("mode") == "rootcheck") {
                val check = BoundedProcessRunner().run({ Runtime.getRuntime().exec(arrayOf("su", "-c", "id")) }, 30000, 1024, 1024)
                publish(if (check.exitCode == 0 && check.stdout.bytes.toString(Charsets.UTF_8).startsWith("uid=0(")) "ROOT_AVAILABLE" else "ROOT_UNAVAILABLE")
                finish(Activity.RESULT_OK, Bundle()); return@runBlocking
            }
            if (arguments.getString("mode") == "recipient") {
                FixtureProfileEnvelope.createRecipient(context.filesDir, id)
                publish("RECIPIENT_READY"); finish(Activity.RESULT_OK, Bundle()); return@runBlocking
            }
            if (arguments.getString("mode") == "release") {
                guard.release(id); publish("DISCONNECTED_CONFIRMED"); finish(Activity.RESULT_OK, Bundle()); return@runBlocking
            }
            val protocol = arguments.getString("protocol") ?: "amneziawg"
            val ipv6 = if (arguments.getString("ipv6") == "tunnel") "tunnel" else "block"
            val apps = AppTrafficSelectionResolver.resolve(AppTrafficSelection(listOf("com.sphereplatform.awgclientprobe"), ipv6 = ipv6), context.packageName, Process.myUid(), AndroidAppIdentitySource(context.packageManager))
            val input = File(context.filesDir, "fixture-client.conf")
            if (File(context.filesDir, "sealed-profile.json").exists()) FixtureProfileEnvelope.open(context.filesDir, id)
            if (input.length() !in 1..65536) throw VpnPreparationException("fixture_config_bounds")
            val prepared = AppScopedConfigPreparation.prepare(input.readText(), protocol, if (protocol == "wireguard") "1" else "3.1", apps)
            input.delete()
            val rootRunner = BoundedProcessRunner()
            val platform = object : ScopedTunPlatform {
                override val ownerUid = Process.myUid()
                override fun assertReady(config: PreparedAppScopedConfig) {
                    if (config.apps.uids.contains(ownerUid)) throw VpnPreparationException("fixture_owner_selected")
                }
                override fun protect(fd: Int): Boolean = true // Root fixture UID is outside all selected UID routes.
                override fun establish(config: PreparedAppScopedConfig): HeldAppTun {
                    val socket = LocalSocket()
                    val descriptor = try {
                        socket.connect(LocalSocketAddress("sphere-awg-fd-$id", LocalSocketAddress.Namespace.ABSTRACT))
                        if (socket.peerCredentials.uid != 0 || socket.inputStream.read() != 'F'.code) throw VpnPreparationException("fixture_fd_sender_invalid")
                        val incoming = socket.ancillaryFileDescriptors ?: throw VpnPreparationException("fixture_fd_missing")
                        if (incoming.size != 1) { incoming.forEach { Os.close(it) }; throw VpnPreparationException("fixture_fd_invalid") }
                        ParcelFileDescriptor.dup(incoming.single()).also { Os.close(incoming.single()) }
                    } finally { socket.close() }
                    val held = HeldDescriptorTun(descriptor)
                    try {
                        val addresses = config.nativeConfig.`interface`.addresses.joinToString("\n") { "ip address add ${it.address.hostAddress}/${it.mask} dev ${held.name}" }
                        val script = "set -eu\ntest \"$(cat /sys/class/net/${held.name}/ifindex)\" = '${held.index}'\n$addresses\nip link set dev ${held.name} mtu 1280 up"
                        if (broker) {
                            runBlocking { rootExecutor.execute(script + "\nprintf '%s\\n' 'SPHERE_FIXTURE_ADDRESS_$id'", "SPHERE_FIXTURE_ADDRESS_$id") }
                        } else {
                            val result = runBlocking { rootRunner.run({ Runtime.getRuntime().exec(arrayOf("su", "-c", script)) }, 10000, 1024, 1024) }
                            if (result.exitCode != 0) throw VpnPreparationException("fixture_address_failed")
                        }
                        return held
                    } catch (failure: Exception) { descriptor.close(); throw failure }
                }
            }
            val session = AppScopedVpnSession(platform, JniScopedAwgEngine(), guard)
            session.connect(id, prepared)
            publish("TRANSPORT_READY")
            repeat(1200) {
                val receipt = session.observe()
                publish(receipt.phase, receipt.stats?.handshakeEpochSeconds ?: 0, receipt.reason)
                if (File(context.filesDir, "disconnect.request").exists()) {
                    session.disconnect(id); publish("DISCONNECTED_CONFIRMED"); finish(Activity.RESULT_OK, Bundle()); return@runBlocking
                }
                delay(100)
            }
            session.disconnect(id); publish("DISCONNECTED_CONFIRMED"); finish(Activity.RESULT_OK, Bundle())
        } catch (failure: Throwable) {
            publish("FAILED", reason = (failure as? VpnPreparationException)?.reason ?: failure.javaClass.simpleName)
            finish(Activity.RESULT_CANCELED, Bundle())
        }
    }
}
