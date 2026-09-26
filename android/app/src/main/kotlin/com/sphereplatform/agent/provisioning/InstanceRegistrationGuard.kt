package com.sphereplatform.agent.provisioning

import com.sphereplatform.agent.store.AuthTokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

/** Проверяет скопированную регистрацию до любого management-трафика с device credentials. */
@Singleton
class InstanceRegistrationGuard @Inject constructor(
    private val authStore: AuthTokenStore,
    private val bindingReader: InstanceBindingReader,
    private val provisioner: ZeroTouchProvisioner,
    private val registration: DeviceRegistrationClient,
) {
    suspend fun ensureRegistered() = withContext(Dispatchers.IO) {
        authStore.enrollmentMutex.withLock {
            val binding = bindingReader.read()
            val bindingVersion = bindingReader.version()
            if (authStore.getInstanceBinding() == binding &&
                authStore.getInstanceBindingVersion() == bindingVersion && authStore.getDeviceId() != null &&
                !authStore.getToken().isNullOrBlank()) return@withLock
            val config = provisioner.discoverConfig()
                ?: throw IOException("Cannot resolve instance registration without provisioning")
            if (!config.requiresRegistration || config.apiKey.isBlank()) {
                throw IOException("Clone-safe registration requires automatic enrollment")
            }
            // Сначала получить и атомарно сохранить полную новую регистрацию.
            // При сетевом отказе прежние токены остаются в хранилище для повторной
            // попытки, но callers обязаны не использовать их до успешного возврата.
            registration.register(config.serverUrl, config.apiKey, fallbackServerUrl = config.fallbackServerUrl,
                instanceBinding = binding, instanceBindingVersion = bindingVersion)
        }
    }
}
