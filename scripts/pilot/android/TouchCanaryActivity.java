package com.sphereplatform.audit.touchinput;

import android.app.Activity;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.FileOutputStream;

/** Disposable receiver proving View delivery independently of injector acknowledgements. */
public final class TouchCanaryActivity extends Activity {
    private int down, move, up, cancel;
    private long firstDownAt, lastMoveAt, terminalAt;
    private float x, y;
    private TextView label;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        label = new TextView(this);
        label.setTextSize(22);
        label.setTextColor(0xffe2e8f0);
        label.setBackgroundColor(0xff0f172a);
        label.setPadding(24, 24, 24, 24);
        label.setOnTouchListener((View view, MotionEvent event) -> {
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN: down++; firstDownAt = SystemClock.uptimeMillis(); break;
                case MotionEvent.ACTION_MOVE: move++; lastMoveAt = SystemClock.uptimeMillis(); break;
                case MotionEvent.ACTION_UP: up++; terminalAt = SystemClock.uptimeMillis(); break;
                case MotionEvent.ACTION_CANCEL: cancel++; terminalAt = SystemClock.uptimeMillis(); break;
                default: return true;
            }
            x = event.getX(); y = event.getY(); persist(); return true;
        });
        setContentView(label);
        persist();
    }

    private void persist() {
        label.setText("Sphere · continuous touch canary\nDOWN " + down + "   MOVE " + move
                + "   UP " + up + "   CANCEL " + cancel + "\nx " + x + "   y " + y);
        try {
            JSONObject state = new JSONObject();
            state.put("down", down); state.put("move", move); state.put("up", up); state.put("cancel", cancel);
            state.put("firstDownUptimeMs", firstDownAt); state.put("lastMoveUptimeMs", lastMoveAt);
            state.put("terminalUptimeMs", terminalAt); state.put("x", x); state.put("y", y);
            // One overwritten, <1 KiB fixture. No captured screen, private app data or growing event log.
            try (FileOutputStream file = openFileOutput("latest.json", MODE_PRIVATE)) {
                file.write(state.toString().getBytes("UTF-8"));
            }
        } catch (Exception failure) { throw new IllegalStateException("canary_state_unavailable"); }
    }
}
