package com.sphereplatform.agent.vpn

import java.io.File
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class AppVpnRestartStoreTest {
    @get:Rule val temporary = TemporaryFolder()
    private val boot = "d4f10294-7bba-4c9e-ab7b-849038e94cc6"
    private val sensitive = "private-restart-fixture-not-a-real-tunnel-key"
    private val command get() = AppVpnCommand.parse("""{"schema_version":2,"request_id":"3c527a55-f375-4a24-a7cf-cb4dfd875ad7","session_id":"6c1641d2-7e46-4148-887c-4d9b91cdc485","action":"apply","profile_revision_id":"346ab6cc-ad1a-4a9b-837e-34cb02cba0f1","profile":{"protocol":"amneziawg","protocol_version":"2","config_text":"$sensitive","traffic_policy":{"mode":"all_apps_except_control","control_plane":"bypass","kill_switch":"all_apps_except_control","ipv6":"block"}}}""")
    private val cipher = object : VpnRestartCipher {
        val key = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
        override fun seal(clear: ByteArray): ByteArray {
            val aes = Cipher.getInstance("AES/GCM/NoPadding"); aes.init(Cipher.ENCRYPT_MODE, key)
            aes.updateAAD("fixture".toByteArray())
            return byteArrayOf(1) + aes.iv + aes.doFinal(clear)
        }
        override fun open(sealed: ByteArray): ByteArray {
            require(sealed[0] == 1.toByte())
            val aes = Cipher.getInstance("AES/GCM/NoPadding")
            aes.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, sealed.copyOfRange(1, 13)))
            aes.updateAAD("fixture".toByteArray())
            return aes.doFinal(sealed, 13, sealed.size - 13)
        }
    }
    @Test fun `encrypted state survives reconstruction and retains pause without plaintext credentials`() {
        val directory = temporary.root
        AppVpnRestartStore(directory, cipher).save(command, boot, paused = true)
        val raw = File(directory, "restart.enc").readBytes()
        assertFalse(raw.toString(Charsets.UTF_8).contains(sensitive))
        val saved = AppVpnRestartStore(directory, cipher).read()!!
        assertEquals(command.sessionId, saved.command.sessionId); assertEquals(boot, saved.bootId); assertTrue(saved.paused)
        assertFalse(saved.toString().contains(sensitive))
    }
    @Test fun `stop wins across process death and only a new explicit apply can enable restoration`() {
        val store = AppVpnRestartStore(temporary.root, cipher)
        store.save(command, boot, false); store.disable()
        assertNull(AppVpnRestartStore(temporary.root, cipher).read())
        try { store.save(command, boot, false); fail() } catch (error: VpnPreparationException) { assertEquals("vpn_restart_disabled", error.reason) }
        assertNull(store.read())
        store.save(command, boot, false, enableAfterStop = true)
        assertNotNull(store.read())
    }
    @Test fun `tampered or oversized ciphertext is rejected with a fixed reason`() {
        val store = AppVpnRestartStore(temporary.root, cipher)
        store.save(command, boot, false)
        val path = File(temporary.root, "restart.enc")
        val sealed = path.readBytes(); sealed[sealed.lastIndex] = (sealed.last().toInt() xor 1).toByte(); path.writeBytes(sealed)
        try { store.read(); fail() } catch (error: VpnPreparationException) { assertEquals("vpn_restart_state_unavailable", error.reason) }
        path.writeBytes(ByteArray(131073))
        try { store.read(); fail() } catch (error: VpnPreparationException) { assertEquals("vpn_restart_state_unavailable", error.reason) }
    }
    @Test fun `failed encryption leaves the existing stop tombstone authoritative`() {
        val store = AppVpnRestartStore(temporary.root, cipher); store.disable()
        val denied = AppVpnRestartStore(temporary.root, object : VpnRestartCipher {
            override fun seal(clear: ByteArray): ByteArray = throw java.io.IOException("fixture")
            override fun open(sealed: ByteArray): ByteArray = throw java.io.IOException("fixture")
        })
        try { denied.save(command, boot, false, enableAfterStop = true); fail() } catch (_: java.io.IOException) { }
        assertNull(store.read())
    }
}
