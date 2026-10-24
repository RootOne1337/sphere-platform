package com.sphereplatform.agent.commands

import android.inputmethodservice.InputMethodService
import android.view.inputmethod.EditorInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicLong

/** Android binds this service under BIND_INPUT_METHOD. It exposes no broadcast or network receiver. */
class RemoteInputMethodService : InputMethodService() {
    private var editorActive = false
    private var generation = 0L
    private var compositionOwner: String? = null
    override fun onCreate() { super.onCreate(); instance = this }
    override fun onStartInput(attribute: EditorInfo?, restarting: Boolean) {
        super.onStartInput(attribute, restarting)
        compositionOwner = null
        generation = nextGeneration.incrementAndGet()
        editorActive = currentInputConnection != null && attribute?.inputType != 0
    }
    override fun onFinishInput() {
        editorActive = false; compositionOwner = null
        generation = nextGeneration.incrementAndGet()
        super.onFinishInput()
    }
    override fun onDestroy() {
        if (instance === this) instance = null
        editorActive = false; compositionOwner = null
        super.onDestroy()
    }
    override fun onEvaluateInputViewShown(): Boolean { super.onEvaluateInputViewShown(); return false }
    override fun onEvaluateFullscreenMode(): Boolean { super.onEvaluateFullscreenMode(); return false }
    companion object {
        @Volatile private var instance: RemoteInputMethodService? = null
        private val nextGeneration = AtomicLong()
        internal suspend fun snapshot(): RemoteKeyboardAdapter.State = withContext(Dispatchers.Main.immediate) {
            val service = instance
            RemoteKeyboardAdapter.State(service != null, service?.generation ?: nextGeneration.get(), service?.editorActive == true)
        }
        internal suspend fun execute(owner: String, command: RemoteKeyboardCommand, current: () -> Boolean): RemoteKeyboardAdapter.Result = withContext(Dispatchers.Main.immediate) {
            if (!current()) return@withContext RemoteKeyboardAdapter.Result.UNAVAILABLE
            val service = instance ?: return@withContext RemoteKeyboardAdapter.Result.UNAVAILABLE
            if (!service.editorActive) return@withContext RemoteKeyboardAdapter.Result.NO_EDITOR
            if (command.editorGeneration != service.generation) return@withContext RemoteKeyboardAdapter.Result.STALE_EDITOR
            val connection = service.currentInputConnection ?: return@withContext RemoteKeyboardAdapter.Result.NO_EDITOR
            try {
                if (service.compositionOwner != null && service.compositionOwner != owner) {
                    if (!connection.finishComposingText()) return@withContext RemoteKeyboardAdapter.Result.UNKNOWN
                    service.compositionOwner = null
                }
                val accepted = when (command.operation) {
                    RemoteKeyboardCommand.Operation.COMMIT -> connection.commitText(checkNotNull(command.text), 1).also { service.compositionOwner = null }
                    RemoteKeyboardCommand.Operation.COMPOSE -> connection.setComposingText(checkNotNull(command.text), 1).also { if (it) service.compositionOwner = owner }
                    RemoteKeyboardCommand.Operation.FINISH, RemoteKeyboardCommand.Operation.RESET -> connection.finishComposingText().also { service.compositionOwner = null }
                    RemoteKeyboardCommand.Operation.DELETE_BACKWARD -> if (!connection.getSelectedText(0).isNullOrEmpty()) connection.commitText("",1)
                        else connection.deleteSurroundingTextInCodePoints(1, 0)
                    RemoteKeyboardCommand.Operation.DELETE_FORWARD -> if (!connection.getSelectedText(0).isNullOrEmpty()) connection.commitText("",1)
                        else connection.deleteSurroundingTextInCodePoints(0, 1)
                    else -> return@withContext RemoteKeyboardAdapter.Result.UNAVAILABLE
                }
                if (accepted) RemoteKeyboardAdapter.Result.ACCEPTED else RemoteKeyboardAdapter.Result.UNKNOWN
            } catch (_: Exception) { RemoteKeyboardAdapter.Result.UNKNOWN }
        }
        internal suspend fun release(owner: String): Boolean = withContext(Dispatchers.Main.immediate) {
            val service = instance ?: return@withContext true
            if (service.compositionOwner != owner) return@withContext true
            service.compositionOwner = null
            runCatching { service.currentInputConnection?.finishComposingText() != false }.getOrDefault(false)
        }
    }
}
