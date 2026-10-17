package com.sphereplatform.agent.commands

import android.content.Context
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteDatabaseCorruptException
import androidx.security.crypto.EncryptedSharedPreferences
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/** Indexed deduplication receipts; command output and errors stay in encrypted preferences/server.
 * No list of historical commands is loaded into the agent heap. Never recreate a lost database.
 */
@Singleton
class CommandReceiptStore internal constructor(
    private val file: File,
    private val preferences: SharedPreferences,
) : AutoCloseable {
    @Inject constructor(@ApplicationContext context: Context, prefs: EncryptedSharedPreferences) :
        this(File(context.noBackupFilesDir, "command-receipts.db"), prefs)

    companion object {
        internal const val IDENTITY_KEY = "command_receipts_database_id"
        internal const val RETENTION_MS = 7L * 24 * 60 * 60 * 1000
        private const val PRUNE_INTERVAL_MS = 60L * 60 * 1000
    }

    data class Receipt(val id: String, val status: String, val acknowledgedAt: Long)
    private var opened: SQLiteDatabase? = null
    private var nextPruneAt = 0L

    private fun database(): SQLiteDatabase {
        opened?.let { return it }
        val expected = preferences.getString(IDENTITY_KEY, null)
        check(expected == null || file.isFile) { "command_receipts_database_missing" }
        check(file.parentFile!!.isDirectory || file.parentFile!!.mkdirs()) { "command_receipts_directory_unavailable" }
        // Android's default corruption handler deletes the database. That would allow replay.
        val db = SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.CREATE_IF_NECESSARY) {
            throw SQLiteDatabaseCorruptException("command_receipts_database_corrupt")
        }
        try {
            db.execSQL("PRAGMA synchronous=FULL")
            if (db.version == 0) {
                check(expected == null) { "command_receipts_database_identity_missing" }
                db.beginTransaction()
                try {
                    db.execSQL("CREATE TABLE identity (id TEXT NOT NULL PRIMARY KEY)")
                    db.execSQL("INSERT INTO identity VALUES (?)", arrayOf(UUID.randomUUID().toString()))
                    db.execSQL("CREATE TABLE receipts (command_id TEXT PRIMARY KEY NOT NULL, status TEXT NOT NULL, acknowledged_at INTEGER NOT NULL)")
                    db.execSQL("CREATE INDEX receipts_age ON receipts(acknowledged_at)")
                    db.version = 1
                    db.setTransactionSuccessful()
                } finally { db.endTransaction() }
            }
            check(db.version == 1) { "command_receipts_database_version_unsupported" }
            val identity = db.rawQuery("SELECT id FROM identity", null).use {
                check(it.moveToFirst()) { "command_receipts_database_identity_missing" }
                val id = it.getString(0)
                check(!it.moveToNext()) { "command_receipts_database_identity_invalid" }
                id
            }
            check(expected == null || expected == identity) { "command_receipts_database_identity_mismatch" }
            if (expected == null) {
                check(preferences.edit().putString(IDENTITY_KEY, identity).commit()) { "command_receipts_identity_write_failed" }
            }
            opened = db
            return db
        } catch (failure: Throwable) {
            db.close()
            throw failure
        }
    }

    @Synchronized fun find(id: String): String? = database().rawQuery(
        "SELECT status FROM receipts WHERE command_id = ?", arrayOf(id),
    ).use { if (it.moveToFirst()) it.getString(0) else null }

    /** Commit before deleting any corresponding encrypted pending record. Retry is idempotent. */
    @Synchronized fun record(receipts: List<Receipt>) {
        val db = database()
        db.beginTransaction()
        try {
            db.compileStatement("INSERT OR IGNORE INTO receipts VALUES (?, ?, ?)").use { statement ->
                for (receipt in receipts) {
                    require(receipt.status in setOf("completed", "failed")) { "command_receipt_not_terminal" }
                    statement.bindString(1, receipt.id)
                    statement.bindString(2, receipt.status)
                    statement.bindLong(3, receipt.acknowledgedAt)
                    statement.executeInsert()
                    check(find(receipt.id) == receipt.status) { "command_receipt_outcome_conflict" }
                }
            }
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }

    @Synchronized fun prune(now: Long) {
        val db = database() // Also verifies storage before admitting the first new command.
        if (now < nextPruneAt) return
        db.delete("receipts", "acknowledged_at < ?", arrayOf((now - RETENTION_MS).toString()))
        nextPruneAt = now + PRUNE_INTERVAL_MS
    }

    @Synchronized override fun close() { opened?.close(); opened = null; nextPruneAt = 0 }
}
