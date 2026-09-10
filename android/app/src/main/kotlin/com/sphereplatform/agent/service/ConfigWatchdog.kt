package com.sphereplatform.agent.service

import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.ws.SphereWebSocketClient
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Polls the configured public discovery endpoint, without device credentials.
 * Periodic and forced checks share one cancellable request. A response may save
 * route candidates only within its service generation and store revision.
 * A healthy selected route remains active until the WS loop authenticates another.
 * Local MDM/file candidates are read at service start; this does not provide server HA.
 */
@Singleton
class ConfigWatchdog @Inject constructor(
    private val provisioner: ZeroTouchProvisioner,
    private val authStore: AuthTokenStore,
    private val wsClient: SphereWebSocketClient,
    private val scope: CoroutineScope,
) {
    companion object {
        private const val DEFAULT_POLL_INTERVAL_MS = 120_000L
        private const val DISCONNECTED_POLL_INTERVAL_MS = 60_000L
    }

    private val stateLock = Any()
    private val runMutex = Mutex()
    private var generation = 0L
    private var stopped = false
    private var checkJob: Job? = null
    private var runJob: Job? = null

    /** The service owns this loop; cancelling it also cancels forced checks. */
    suspend fun run() = coroutineScope {
        if (!runMutex.tryLock()) return@coroutineScope
        val owner = currentCoroutineContext()[Job]!!
        val runGeneration = synchronized(stateLock) {
            checkJob?.cancel()
            checkJob = null
            stopped = false
            runJob = owner
            ++generation
        }
        try {
            val initialRoute = authStore.serverUrlSnapshot()
            try {
                withContext(Dispatchers.IO) { provisioner.discoverLocalConfig() }?.let { local ->
                    applyCandidates(runGeneration, initialRoute, local.serverUrl, local.fallbackServerUrl)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Timber.w("ConfigWatchdog: local route config failed (%s)", e.javaClass.simpleName)
            }
            if (!provisioner.hasConfigEndpoint) return@coroutineScope
            delay(5_000L)
            while (isActive) {
                requestCheck(runGeneration)?.join()
                delay(if (wsClient.isConnected) DEFAULT_POLL_INTERVAL_MS else DISCONNECTED_POLL_INTERVAL_MS)
            }
        } finally {
            synchronized(stateLock) {
                if (generation == runGeneration) stopLocked(cancelLoop = false)
            }
            runMutex.unlock()
        }
    }

    fun stop() = synchronized(stateLock) { stopLocked() }

    private fun stopLocked(cancelLoop: Boolean = true) {
        stopped = true
        ++generation
        checkJob?.cancel()
        checkJob = null
        if (cancelLoop) runJob?.cancel()
        runJob = null
    }

    /** Repeated notifications coalesce while a request is active. */
    fun forceCheck() {
        requestCheck()
    }

    private fun requestCheck(expectedGeneration: Long? = null): Job? = synchronized(stateLock) {
        if (stopped || (expectedGeneration != null && expectedGeneration != generation)) return null
        checkJob?.takeIf { it.isActive }?.let { return it }
        val checkGeneration = generation
        scope.launch(Dispatchers.IO, start = CoroutineStart.LAZY) {
            try {
                checkAndUpdate(checkGeneration)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Timber.w("ConfigWatchdog: check failed (%s)", e.javaClass.simpleName)
            }
        }.also { checkJob = it; it.start() }
    }

    private suspend fun checkAndUpdate(checkGeneration: Long) {
        val route = authStore.serverUrlSnapshot()
        val config = provisioner.fetchServerConfig() ?: return
        val remoteUrl = config.serverUrl.trimEnd('/')
        applyCandidates(checkGeneration, route, remoteUrl, config.fallbackServerUrl)
    }

    private suspend fun applyCandidates(checkGeneration: Long, route: AuthTokenStore.ServerUrlSnapshot,
                                        remoteUrl: String, fallbackUrl: String?) {
        val context = currentCoroutineContext()
        synchronized(stateLock) {
            context.ensureActive()
            if (stopped || generation != checkGeneration) return
            if (route.url.isBlank()) return
            if (!authStore.replaceDiscoveredRoutes(route, remoteUrl, fallbackUrl)) {
                Timber.d("ConfigWatchdog: route candidates unchanged or superseded")
                return
            }
            Timber.i("ConfigWatchdog: management route candidates saved")
            // A candidate must not tear down a working authenticated connection.
            if (!wsClient.isConnected) wsClient.forceReconnectNow()
        }
    }
}
