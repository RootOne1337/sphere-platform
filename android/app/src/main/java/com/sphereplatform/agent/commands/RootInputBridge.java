package com.sphereplatform.agent.commands;

import android.os.Build;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import java.lang.reflect.Method;

/** Invoked only as root by app_process with the installed APK on CLASSPATH. */
public final class RootInputBridge {
    public static void main(String[] args) {
        try {
            if (android.os.Process.myUid() != 0 || args.length != 1 || !"clear-focused".equals(args[0])) {
                throw new IllegalArgumentException("input_clear_privileged_adapter_required");
            }
            String managerName = Build.VERSION.SDK_INT >= 34
                    ? "android.hardware.input.InputManagerGlobal" : "android.hardware.input.InputManager";
            Class<?> managerClass = Class.forName(managerName);
            Object manager = managerClass.getMethod("getInstance").invoke(null);
            Method inject = managerClass.getMethod("injectInputEvent", InputEvent.class, int.class);
            long downTime = SystemClock.uptimeMillis();
            RootTextClearSequence.clear((action, code, meta) -> {
                KeyEvent event = new KeyEvent(downTime, SystemClock.uptimeMillis(), action, code,
                        0, meta, KeyCharacterMap.VIRTUAL_KEYBOARD, 0, 0, InputDevice.SOURCE_KEYBOARD);
                // WAIT_FOR_FINISH: queue acceptance alone does not allow the next DAG input.
                return Boolean.TRUE.equals(inject.invoke(manager, event, 2));
            });
        } catch (Throwable failure) {
            // No typed value, editor contents or reflection/platform exception in logs.
            System.err.println("input_clear_adapter_failed");
            System.exit(1);
        }
    }

    private RootInputBridge() {}
}
