package com.sphereplatform.audit;

import android.content.Context;
import android.content.ContextWrapper;
import android.os.Looper;
import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;
import com.sphereplatform.agent.commands.CommandJournal;
import com.sphereplatform.agent.commands.CommandReceiptStore;
import java.io.File;
import java.security.KeyStore;
import java.util.UUID;
import org.json.JSONObject;

/** Explicit app_process probe, never bundled in the APK. Run as the owned app UID.
 * Uses fresh, isolated encrypted preferences, keystore alias and SQLite file.
 * No network, dispatcher, device actions, real journal or real credentials are accessed.
 */
public final class JournalStorageProbe {
    private static final class ProbeContext extends ContextWrapper {
        ProbeContext(Context base) { super(base); }
        @Override public Context getApplicationContext() { return this; }
    }
    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalStateException(message);
    }

    public static void main(String[] args) {
        int exit = 1;
        Context context = null;
        String name = "sphere-journal-probe-" + UUID.randomUUID();
        File database = null;
        CommandReceiptStore store = null;
        try {
            require(args.length == 1 && args[0].startsWith("com.sphereplatform.agent."), "owned_package_required");
            require(android.os.Build.VERSION.SDK_INT == 28, "probe_bootstrap_requires_api_28");
            Looper.prepareMainLooper();
            Class<?> threadType = Class.forName("android.app.ActivityThread");
            Object thread = threadType.getMethod("systemMain").invoke(null);
            Context system = (Context) threadType.getMethod("getSystemContext").invoke(thread);
            context = new ProbeContext(system.createPackageContext(args[0], Context.CONTEXT_IGNORE_SECURITY));
            // app_process does not inherit Zygote's JCA provider initialization.
            Class.forName("android.security.keystore.AndroidKeyStoreProvider")
                .getMethod("install").invoke(null);
            // API 28's compatibility-WAL initializer otherwise asks ActivityManager
            // for a registered app thread. This separate test process uses defaults.
            Class.forName("android.database.sqlite.SQLiteCompatibilityWalFlags")
                .getMethod("init", String.class).invoke(null, "");
            MasterKey key = new MasterKey.Builder(context, name).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build();
            EncryptedSharedPreferences prefs = (EncryptedSharedPreferences) EncryptedSharedPreferences.create(
                context, name, key, EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
            database = new File(context.getNoBackupFilesDir(), name + ".db");
            require(!database.exists(), "fresh_probe_database_required");
            JSONObject old = new JSONObject();
            for (int i = 0; i < 512; i++) {
                old.put("legacy-" + i, new JSONObject().put("created_at", System.currentTimeMillis())
                    .put("acknowledged", true).put("response", new JSONObject()
                    .put("type", "command_result").put("command_id", "legacy-" + i)
                    .put("status", i == 0 ? "failed" : "completed")));
            }
            require(prefs.edit().putString("command_journal_v1", old.toString()).commit(), "seed_commit_failed");
            store = new CommandReceiptStore(database, prefs);
            CommandJournal journal = new CommandJournal(prefs, store);
            require(journal.claim("undelivered") instanceof CommandJournal.Claim.Started, "migration_admission_failed");
            journal.complete("undelivered", "failed", "isolated pending evidence", null);
            long started = System.nanoTime();
            for (int i = 0; i < 2048; i++) {
                String id = "fresh-" + i;
                require(journal.claim(id) instanceof CommandJournal.Claim.Started, "fresh_admission_failed");
                journal.complete(id, "completed", null, null);
                journal.acknowledge(id);
            }
            store.close();
            store = new CommandReceiptStore(database, prefs);
            journal = new CommandJournal(prefs, store);
            require("failed".equals(store.find("legacy-0")), "migration_lost_failed_outcome");
            require(journal.claim("legacy-0") instanceof CommandJournal.Claim.Existing, "legacy_replayed");
            require(journal.claim("fresh-0") instanceof CommandJournal.Claim.Existing, "fresh_replayed");
            require(journal.claim("fresh-2047") instanceof CommandJournal.Claim.Existing, "last_replayed");
            require(journal.pending().size() == 1, "undelivered_result_lost");
            journal.acknowledge("undelivered");
            require(journal.pending().isEmpty(), "pending_not_released");
            require(journal.claim("after-reopen") instanceof CommandJournal.Claim.Started, "reopen_admission_failed");
            journal.complete("after-reopen", "completed", null, null);
            journal.acknowledge("after-reopen");
            System.out.println(new JSONObject().put("passed", true).put("migrated_acknowledgements", 512)
                .put("new_acknowledgements", 2048).put("database_reopened", true)
                .put("pending_preserved", true).put("duplicate_execution_admitted", false)
                .put("elapsed_ms", (System.nanoTime() - started) / 1_000_000)
                .put("database_bytes", database.length()).put("device_actions", 0).toString());
            exit = 0;
        } catch (Throwable failure) {
            failure.printStackTrace();
        } finally {
            if (store != null) store.close();
            if (context != null) context.deleteSharedPreferences(name);
            if (database != null) {
                // Only the UUID-named probe files; never the application's command-receipts.db.
                for (String suffix : new String[] {"", "-journal", "-wal", "-shm"}) {
                    File probe = new File(database.getPath() + suffix);
                    if (probe.exists() && !probe.delete()) exit = 1;
                }
            }
            try {
                KeyStore keys = KeyStore.getInstance("AndroidKeyStore");
                keys.load(null);
                keys.deleteEntry(name);
            } catch (Exception cleanupFailure) { exit = 1; }
        }
        System.exit(exit);
    }
}
