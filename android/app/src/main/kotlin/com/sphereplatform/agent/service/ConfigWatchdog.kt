package com.sphereplatform.agent.service

import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.ws.SphereWebSocketClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * ConfigWatchdog — периодический опрос удалённого конфига (GitHub Raw / Config Endpoint).
 *
 * Цикл работы:
 *   1. Каждые [DEFAULT_POLL_INTERVAL_MS] (5 мин) запрашивает CONFIG_URL
 *   2. Парсит ответ через [ZeroTouchProvisioner.fetchServerConfig]
 *   3. Если server_url в ответе отличается от сохранённого в [AuthTokenStore]:
 *      - Атомарно обновляет store
 *      - Вызывает [SphereWebSocketClient.forceReconnectNow] для немедленного переподключения
 *
 * Когда WS не подключён — интервал сокращается до 60с (ускоренный поиск нового адреса).
 *
 * Гарантирует отказоустойчивость: если tunnel/server сменился, агент автоматически
 * подхватит новый URL из Git-репозитория без ручного вмешательства.
 */
@Singleton
class ConfigWatchdog @Inject constructor(
    private val provisioner: ZeroTouchProvisioner,
    private val authStore: AuthTokenStore,
    private val wsClient: SphereWebSocketClient,
    private val scope: CoroutineScope,
) {
    companion object {
        /** Минимальный интервал опроса (защита от слишком частых запросов) */
        private const val MIN_POLL_INTERVAL_MS = 15_000L

        /** Стандартный интервал когда WS подключён (2 минуты) */
        private const val DEFAULT_POLL_INTERVAL_MS = 120_000L

        /** Ускоренный интервал когда WS отключён.
         * FIX M4: 60с вместо 30с — на слабых эмуляторах 30с polling
         * вместе с WS reconnect loop создаёт избыточный network/CPU pressure.
         */
        private const val DISCONNECTED_POLL_INTERVAL_MS = 60_000L
    }

    @Volatile
    private var running = false

    /**
     * Основной цикл. Запускается как coroutine в [SphereAgentService].
     * Все исключения обрабатываются внутри — наружу не пробрасываются.
     */
    suspend fun run() {
        if (BuildConfig.CONFIG_URL.isBlank()) {
            Timber.w("ConfigWatchdog: CONFIG_URL пуст — remote config отключён")
            return
        }

        running = true
        Timber.i("ConfigWatchdog: запущен, CONFIG_URL=${BuildConfig.CONFIG_URL.take(80)}…")

        // Первичная задержка — даём WS-клиенту установить начальное соединение
        // FIX-CONFIG: 5с вместо 15с — быстрее обнаруживаем новый URL при смене туннеля
        delay(5_000L)

        while (running) {
            try {
                checkAndUpdate()
            } catch (e: Exception) {
                Timber.w(e, "ConfigWatchdog: ошибка проверки конфига")
            }

            // Ускоренный polling если WS не подключён (ищем новый server_url)
            val interval = if (wsClient.isConnected) {
                DEFAULT_POLL_INTERVAL_MS
            } else {
                DISCONNECTED_POLL_INTERVAL_MS
            }
            delay(interval.coerceAtLeast(MIN_POLL_INTERVAL_MS))
        }
    }

    /** Остановка цикла (вызывается при onDestroy сервиса). */
    fun stop() {
        running = false
    }

    /**
     * Принудительная проверка конфига — вызывается при circuit breaker open
     * или при длительном отсутствии соединения.
     *
     * FIX-RECONNECT: Запускается через IO dispatcher чтобы не блокировать WS reconnect loop.
     */
    fun forceCheck() {
        Timber.d("ConfigWatchdog: принудительная проверка конфига")
        scope.launch(Dispatchers.IO) {
            try {
                checkAndUpdate()
            } catch (e: Exception) {
                Timber.w(e, "ConfigWatchdog: ошибка принудительной проверки")
            }
        }
    }

    /**
     * Запрашивает конфиг с сервера и при необходимости обновляет server_url.
     *
     * Выполняется синхронно (блокирующий HTTP-вызов) — вызывать из IO-контекста.
     */
    private fun checkAndUpdate() {
        val serverConfig = provisioner.fetchServerConfig(
            apiKey = authStore.getToken()
        )

        if (serverConfig == null) {
            Timber.d("ConfigWatchdog: config endpoint недоступен")
            return
        }

        val currentUrl = authStore.getServerUrl().trimEnd('/')
        val remoteUrl = serverConfig.serverUrl.trimEnd('/')

        if (remoteUrl.isBlank()) {
            Timber.d("ConfigWatchdog: remote server_url пуст — пропускаем")
            return
        }

        if (currentUrl.isNotBlank() && currentUrl != remoteUrl) {
            Timber.w(
                "ConfigWatchdog: SERVER_URL ИЗМЕНИЛСЯ! " +
                    "old=$currentUrl → new=$remoteUrl — обновляем и переподключаемся"
            )
            authStore.saveServerUrl(remoteUrl)

            // Форсируем немедленный reconnect на новый адрес (прерывает текущий backoff/circuit)
            wsClient.forceReconnectNow()
        } else {
            Timber.d("ConfigWatchdog: server_url актуален ($remoteUrl)")
        }
    }
}
