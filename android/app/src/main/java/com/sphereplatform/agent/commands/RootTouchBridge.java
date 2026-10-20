package com.sphereplatform.agent.commands;

import android.os.Build;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.MotionEvent;
import android.view.KeyEvent;
import android.view.KeyCharacterMap;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.lang.reflect.Method;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Privileged app_process entry point. Stdio belongs exclusively to the agent that launched it. */
public final class RootTouchBridge {
    public static void main(String[] args) {
        RootTouchSession session = null;
        ScheduledExecutorService watchdog = null;
        DataOutputStream output = new DataOutputStream(System.out);
        int exitCode = 0;
        boolean readyPublicationAttempted = false;
        String startupDetail = "root_required";
        try {
            if (android.os.Process.myUid() != 0 || args.length != 4 || !"touch-v1".equals(args[0])) {
                throw new IllegalArgumentException("touch_privileged_adapter_required");
            }
            // Keep the owned injector responsive while software video encoding
            // is CPU-bound. No realtime policy, extra permission or global change.
            try { android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_DISPLAY); }
            catch (SecurityException unavailable) { System.err.println("touch_priority_unavailable"); }
            startupDetail = "root_configuration";
            int width = Integer.parseInt(args[1]), height = Integer.parseInt(args[2]), rotation = Integer.parseInt(args[3]);
            if (width > 16384 || height > 16384 || rotation < 0 || rotation > 3) throw new IllegalArgumentException("touch_geometry_invalid");
            String managerName = Build.VERSION.SDK_INT >= 34
                    ? "android.hardware.input.InputManagerGlobal" : "android.hardware.input.InputManager";
            startupDetail = "root_adapter_unavailable";
            Class<?> managerClass = Class.forName(managerName);
            Object manager = managerClass.getMethod("getInstance").invoke(null);
            Method inject = managerClass.getMethod("injectInputEvent", InputEvent.class, int.class);
            Class<?> displays = Class.forName("android.hardware.display.DisplayManagerGlobal");
            Object displayManager = displays.getMethod("getInstance").invoke(null);
            Method getInfo = displays.getMethod("getDisplayInfo", int.class);
            RootTouchSession.Geometry geometry = () -> {
                Object info = getInfo.invoke(displayManager, 0);
                if (info == null) return false;
                Class<?> type = info.getClass();
                return type.getField("logicalWidth").getInt(info) == width
                        && type.getField("logicalHeight").getInt(info) == height
                        && type.getField("rotation").getInt(info) == rotation;
            };
            startupDetail = "root_geometry";
            if (!geometry.matches()) throw new IllegalArgumentException("touch_geometry_invalid");
            session = new RootTouchSession(width, height, SystemClock.uptimeMillis(), (action, x, y, down, now) -> {
                MotionEvent.PointerProperties finger = new MotionEvent.PointerProperties();
                finger.id = 0;
                finger.toolType = MotionEvent.TOOL_TYPE_FINGER;
                MotionEvent.PointerCoords point = new MotionEvent.PointerCoords();
                point.x = x; point.y = y; point.size = 1f;
                point.pressure = action == RootTouchSession.UP || action == RootTouchSession.CANCEL ? 0f : 1f;
                MotionEvent event = MotionEvent.obtain(down, now, action, 1,
                        new MotionEvent.PointerProperties[]{finger}, new MotionEvent.PointerCoords[]{point},
                        0, 0, 1f, 1f, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
                try {
                    // Live pointer events use ordered ASYNC submission, just like
                    // interactive keys. A physical touch or another participant
                    // may change focus/replace the stream while Android dispatches
                    // it. Waiting on that transient target can refuse DOWN/UP and
                    // unnecessarily retire every live participant. Native ACK is
                    // submission acceptance, not application/display completion.
                    // CANCEL is cleanup only; no interrupted action is replayed.
                    return Boolean.TRUE.equals(inject.invoke(manager, event, 0));
                } finally { event.recycle(); }
            }, geometry, (action, code, meta, down, now) -> {
                boolean cleanup = action == RootTouchSession.KEY_RELEASE;
                KeyEvent event = new KeyEvent(down, now, cleanup ? KeyEvent.ACTION_UP : action,
                        code, 0, meta, KeyCharacterMap.VIRTUAL_KEYBOARD, 0,
                        KeyEvent.FLAG_FROM_SYSTEM | (cleanup ? KeyEvent.FLAG_CANCELED : 0), InputDevice.SOURCE_KEYBOARD);
                // Interactive keys may themselves change focus (Home/Recents)
                // while another participant queues a key. WAIT_FOR_RESULT ties
                // this ordered input pipe to that transient focused window and
                // can refuse the next edge. Submit both edges asynchronously,
                // as remote-control input, preserving order and exact pipe ACK.
                // ACK means native submission, never application completion.
                return Boolean.TRUE.equals(inject.invoke(manager, event, 0));
            });
            RootTouchSession owned = session;
            watchdog = Executors.newSingleThreadScheduledExecutor();
            watchdog.scheduleAtFixedRate(() -> {
                RootTouchSession.Result result;
                synchronized (owned) {
                    // Sample uptime after acquiring the state lock. Sampling before it could
                    // falsely look like clock regression when the reader and watchdog race.
                    result = owned.tick(SystemClock.uptimeMillis());
                }
                if (result != null) {
                    try { RootTouchWire.ack(output, 0, result.wireCode, SystemClock.uptimeMillis()); }
                    catch (Exception ignored) { /* The pipe may already have closed. */ }
                    // The outcome ACK still rejects expired input. A normal exit separately
                    // proves known cleanup so a later owner is not permanently fenced.
                    System.exit(owned.cleanupExitCode());
                }
            }, 100, 100, TimeUnit.MILLISECONDS);
            startupDetail = "root_handshake";
            // A failed flush can follow delivery of READY. Mark before writing;
            // that failure must never be described as a known pre-input refusal.
            readyPublicationAttempted = true;
            RootTouchWire.ack(output, 0, 0, SystemClock.uptimeMillis());
            DataInputStream input = new DataInputStream(System.in);
            while (!session.isClosed()) {
                RootTouchWire.Packet packet = RootTouchWire.read(input);
                RootTouchSession.Result result;
                synchronized (session) {
                    result = session.apply(packet.sequence, packet.gesture, packet.action, packet.x, packet.y, SystemClock.uptimeMillis());
                }
                RootTouchWire.ack(output, packet.sequence, result.wireCode, SystemClock.uptimeMillis());
                if (session.isClosed()) exitCode = session.cleanupExitCode();
            }
        } catch (EOFException endOfOwnerPipe) {
            // Normal owner teardown or a truncated packet: both retire the session and cancel locally.
        } catch (Throwable failure) {
            // No coordinates, contents, shell command, token or reflection/platform exception in logs.
            if (!readyPublicationAttempted) {
                System.err.println("touch_startup_" + startupDetail);
                try {
                    RootTouchWire.ack(output, 0, 5, SystemClock.uptimeMillis());
                    exitCode = 3; // Dedicated startup-refusal exit, never a release after input.
                } catch (Exception unknown) { exitCode = 1; }
            } else {
                System.err.println("touch_adapter_failed");
                exitCode = 1;
            }
        } finally {
            if (watchdog != null) watchdog.shutdownNow();
            if (session != null && session.close(SystemClock.uptimeMillis()) == RootTouchSession.Result.UNKNOWN) exitCode = 2;
        }
        if (exitCode != 0) System.exit(exitCode);
    }
    private RootTouchBridge() {}
}
