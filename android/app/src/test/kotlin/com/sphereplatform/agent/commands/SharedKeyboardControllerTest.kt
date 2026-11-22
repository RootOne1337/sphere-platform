package com.sphereplatform.agent.commands

import com.sphereplatform.agent.direct.DirectInputChannel
import com.sphereplatform.agent.streaming.CaptureInputSession
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.CopyOnWriteArrayList

class SharedKeyboardControllerTest {
    private class Keyboard : RemoteKeyboardAdapter {
        val owners=java.util.concurrent.ConcurrentHashMap.newKeySet<String>()
        val commands=CopyOnWriteArrayList<RemoteKeyboardCommand>()
        @Volatile var result=RemoteKeyboardAdapter.Result.ACCEPTED
        override suspend fun enable(owner:String):Boolean { owners+=owner;return true }
        override suspend fun disable(owner:String):Boolean { owners-=owner;return true }
        override suspend fun reset():Boolean { owners.clear();return true }
        override fun state()=RemoteKeyboardAdapter.State(owners.isNotEmpty(),7,true)
        override suspend fun apply(owner:String,command:RemoteKeyboardCommand,current:()->Boolean):RemoteKeyboardAdapter.Result {
            assertTrue(current());commands+=command;return result
        }
        override suspend fun release(owner:String)=true
    }
    @Test fun `same authorized participant carries Unicode and explicit refusal without breaking pointer input`()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val keyboard=Keyboard();val messages=CopyOnWriteArrayList<JsonObject>()
        val capture=CaptureInputSession("00112233-4455-6677-8899-aabbccddeeff",960,540,960,540,0)
        val controller=SharedDirectInputController(scope,TouchPipeFactory {
            val native=RootTouchSession(960,540,1000,{_,_,_,_,_->true},{true},{_,_,_,_,_->true})
            object:TouchPipe {
                override suspend fun send(sample:TouchSample):RootTouchWire.Ack {
                    val result=native.apply(sample.sequence,sample.gesture,sample.action,sample.x,sample.y,1000)
                    val bytes=ByteArrayOutputStream();RootTouchWire.ack(bytes,sample.sequence,result.wireCode,1000)
                    return RootTouchWire.readAck(ByteArrayInputStream(bytes.toByteArray()))
                }
                override suspend fun closeAndConfirm():Boolean {native.close(1000);return native.cleanupExitCode()==0}
            }
        },{capture},{1000},keyboard=keyboard)
        val peer=object:DirectInputChannel {
            override val keyboardSupported=true
            override val session="a".repeat(32);override val capture=capture
            override fun isCurrent()=true
            override fun send(message:JsonObject):Boolean {messages+=message;return true}
        }
        suspend fun await(predicate:()->Boolean) {withTimeout(3000){while(!predicate())delay(5)}}
        try {
            assertTrue(controller.grant(peer))
            assertTrue(controller.message(peer.session,buildJsonObject {put("type","touch_open");put("capture_epoch",capture.epoch);put("frame_width",960);put("frame_height",540)}))
            await {messages.any{it["outcome"]==JsonPrimitive("ready")}}
            assertTrue(controller.message(peer.session,buildJsonObject {put("type","keyboard_mode");put("enabled",true)}))
            await {messages.any{it["type"]==JsonPrimitive("keyboard_state")&&it["enabled"]==JsonPrimitive(true)}}
            fun commit(seq:Int)=controller.message(peer.session,buildJsonObject {put("type","keyboard_event");put("sequence",seq);put("operation","commit");put("editor_generation",7);put("text","Привет 🙂")})
            assertTrue(commit(1));await {messages.any{it["type"]==JsonPrimitive("keyboard_result")&&it["outcome"]==JsonPrimitive("accepted")}}
            keyboard.result=RemoteKeyboardAdapter.Result.STALE_EDITOR
            assertTrue(commit(2));await {messages.any{it["type"]==JsonPrimitive("keyboard_result")&&it["outcome"]==JsonPrimitive("stale_editor")}}
            assertEquals(2,keyboard.commands.size)
            assertTrue(messages.none{it.toString().contains("Привет")||it.containsKey("text")})
            assertTrue(controller.message(peer.session,buildJsonObject {put("type","touch_event");put("sequence",3);put("gesture",1);put("action",0);put("x",10);put("y",20)}))
            await {messages.any{it["sequence"]==JsonPrimitive(3)&&it["outcome"]==JsonPrimitive("applied")}}
            controller.closed(peer.session)
            await {keyboard.owners.isEmpty()}
        } finally {scope.cancel()}
    }
}
