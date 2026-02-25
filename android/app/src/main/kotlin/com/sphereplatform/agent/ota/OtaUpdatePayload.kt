package com.sphereplatform.agent.ota

import kotlinx.serialization.Serializable

@Serializable
data class OtaUpdatePayload(
    val download_url: String,
    val version: String,
    val sha256: String,
    val force: Boolean = false,
)
