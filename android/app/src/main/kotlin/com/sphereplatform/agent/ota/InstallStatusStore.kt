package com.sphereplatform.agent.ota

import android.content.Context
import android.content.pm.PackageInstaller

/** Minimal, process-independent handoff from PackageInstaller's broadcast to OTA work. */
internal object InstallStatusStore {
    private const val PREFERENCES = "sphere_ota_install_status_v1"
    private const val ACTIVE_SESSION_ID = "active_session_id"
    private const val STATUS = "status"

    fun begin(context: Context, sessionId: Int): Boolean =
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .putInt(ACTIVE_SESSION_ID, sessionId)
            .remove(STATUS)
            .commit()

    /** Ignore late callbacks for a superseded session; only one OTA install is active per process. */
    fun record(context: Context, sessionId: Int, status: Int): Boolean {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (sessionId < 0 || preferences.getInt(ACTIVE_SESSION_ID, -1) != sessionId) return false
        return preferences.edit().putInt(STATUS, status).commit()
    }

    fun read(context: Context, sessionId: Int): Int? {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        if (preferences.getInt(ACTIVE_SESSION_ID, -1) != sessionId || !preferences.contains(STATUS)) return null
        return preferences.getInt(STATUS, PackageInstaller.STATUS_FAILURE)
    }

    /** Listen for a terminal or pending-approval result without polling the device. */
    fun observe(context: Context, sessionId: Int, onStatus: (Int) -> Unit): () -> Unit {
        val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
        val listener = android.content.SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == ACTIVE_SESSION_ID || key == STATUS) {
                read(context, sessionId)?.let(onStatus)
            }
        }
        preferences.registerOnSharedPreferenceChangeListener(listener)
        return { preferences.unregisterOnSharedPreferenceChangeListener(listener) }
    }
}
