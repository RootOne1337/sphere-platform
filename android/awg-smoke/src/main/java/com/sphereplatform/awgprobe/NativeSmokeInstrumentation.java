package com.sphereplatform.awgprobe;

import android.app.Instrumentation;
import android.app.Activity;
import android.os.Bundle;
import org.amnezia.awg.GoBackend;

/** No VpnService, consent, TUN creation, socket, route or credential operations. */
public final class NativeSmokeInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            System.loadLibrary("wg-go");
            String version = GoBackend.awgVersion();
            if (version == null || version.isEmpty() || version.length() > 128) throw new IllegalStateException();
            if (GoBackend.awgGetConfig(-1) != null || GoBackend.awgGetSocketV4(-1) != -1 || GoBackend.awgGetSocketV6(-1) != -1) throw new IllegalStateException();
            GoBackend.awgTurnOff(-1);
            result.putString("nativeVersion", version);
            result.putBoolean("jniReadOnlyPassed", true);
            result.putBoolean("tunCreated", false);
            finish(Activity.RESULT_OK, result);
        } catch (Throwable error) {
            // Never report native config, keys or raw exception messages.
            result.putString("failure", error.getClass().getSimpleName());
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
