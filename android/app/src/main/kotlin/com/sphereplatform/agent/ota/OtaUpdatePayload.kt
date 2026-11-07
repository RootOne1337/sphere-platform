package com.sphereplatform.agent.ota

import kotlinx.serialization.Serializable

@Serializable
data class OtaUpdatePayload(
    val download_url: String,
    val version: String,
    val sha256: String,
    val version_code: Int = 0,
    val force: Boolean = false,
)
