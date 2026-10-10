package com.sphereplatform.agent.direct

/** Only fixed stage names can enter diagnostics; never native errors, SDP or addresses. */
internal enum class ProbeStage(val wireName: String, val terminal: Boolean = false) {
    OFFER_RECEIVED("offer_received"), FACTORY_READY("factory_ready"), PEER_READY("peer_ready"),
    REMOTE_SET("remote_description_set"), ANSWER_CREATED("answer_created"),
    LOCAL_SET("local_description_set"), GATHERING("gathering"), GATHERED("gathered"),
    ANSWER_SENT("answer_sent"), CHANNEL_RECEIVED("channel_received"), CHANNEL_OPEN("channel_open"),
    REMOTE_FAILED("remote_description_failed", true), CREATE_FAILED("answer_creation_failed", true),
    LOCAL_FAILED("local_description_failed", true), OPEN_FAILED("peer_setup_failed", true),
    ANSWER_FAILED("answer_delivery_failed", true), CONNECTION_FAILED("connection_failed", true),
    CLOSED("closed", true), EXPIRED("expired", true),
}

internal data class ProbeProgressSnapshot(val stage: ProbeStage, val elapsedMs: Long)

/** Actor-owned, <=one event per stage and no events after retirement, regardless of callbacks. */
internal class DirectProbeProgress(private val startedAt: Long) {
    private val seen = mutableSetOf<ProbeStage>()
    private var retired = false
    private var lastAt = startedAt

    fun record(stage: ProbeStage, now: Long): ProbeProgressSnapshot? {
        if (retired || startedAt < 0 || now < lastAt || !seen.add(stage)) return null
        lastAt = now
        if (stage.terminal) retired = true
        return ProbeProgressSnapshot(stage, (now - startedAt).coerceAtMost(DirectProbeProtocol.MAX_TTL_MS.toLong()))
    }
}
