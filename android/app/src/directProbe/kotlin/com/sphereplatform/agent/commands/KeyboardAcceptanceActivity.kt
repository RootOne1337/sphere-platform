package com.sphereplatform.agent.commands

import android.app.Activity
import android.os.Bundle
import android.text.InputType
import android.view.KeyEvent
import android.view.MotionEvent
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.widget.AppCompatTextView
import com.sphereplatform.agent.BuildConfig

/** Small real Android editor/game fixture for an explicitly launched debug-canary acceptance. */
class KeyboardAcceptanceActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!BuildConfig.DEBUG || !BuildConfig.CONTINUOUS_INPUT_CANARY) { finish(); return }
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(16,16,16,16) }
        fun editor(description: String) = EditText(this).apply {
            contentDescription = description; hint = description
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            maxLines = 3; minLines = 2; textSize = 18f
            layout.addView(this, LinearLayout.LayoutParams(-1,0,1f))
        }
        val first = editor("Keyboard acceptance first")
        editor("Keyboard acceptance second")
        val game = object : AppCompatTextView(this) {
            private var down = 0; private var up = 0; private var last = 0
            override fun onTouchEvent(event: MotionEvent): Boolean {
                if (event.action == MotionEvent.ACTION_DOWN) { requestFocus(); performClick() }; return true
            }
            override fun performClick(): Boolean { super.performClick(); return true }
            override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
                down++; last=keyCode; text="Game keys DOWN=$down UP=$up LAST=$last"; return true
            }
            override fun onKeyUp(keyCode: Int, event: KeyEvent): Boolean {
                up++; last=keyCode; text="Game keys DOWN=$down UP=$up LAST=$last"; return true
            }
        }.apply {
            contentDescription="Keyboard acceptance game"; text="Game keys DOWN=0 UP=0 LAST=0"
            isFocusableInTouchMode=true; textSize=18f; setPadding(12,12,12,12)
            layout.addView(this,LinearLayout.LayoutParams(-1,0,1f))
        }
        setContentView(layout); first.requestFocus()
    }
}
