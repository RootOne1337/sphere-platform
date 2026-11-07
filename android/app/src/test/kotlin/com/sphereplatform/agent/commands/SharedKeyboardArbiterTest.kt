package com.sphereplatform.agent.commands

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class SharedKeyboardArbiterTest {
    @Test fun `latest participant resets held modifiers before pointer takeover and ignores old up`() = runBlocking {
        val sent=mutableListOf<SharedPointerArbiter.NativeAction>()
        val a="participant_A_1234";val b="participant_B_1234"
        val arbiter=SharedPointerArbiter(960,540,{1000}){sent+=it;true}
        arbiter.attach(a,5000,true);arbiter.attach(b,5000,true)
        fun key(id:String,seq:Int,op:RemoteKeyboardCommand.Operation,code:Int)=SharedPointerArbiter.Event(id,seq,0,9,0,0,1000,
            RemoteKeyboardCommand(op,0,keyCode=code,meta=4096))
        assertEquals(SharedPointerArbiter.Outcome.APPLIED,arbiter.offer(key(a,1,RemoteKeyboardCommand.Operation.KEY_DOWN,113)).single().outcome)
        arbiter.offer(key(a,2,RemoteKeyboardCommand.Operation.KEY_DOWN,29))
        arbiter.offer(SharedPointerArbiter.Event(b,1,1,0,10,20,1000))
        assertEquals(listOf(6,6,8,0),sent.map{it.action})
        assertEquals(SharedPointerArbiter.Outcome.INTERRUPTED,arbiter.offer(key(a,3,RemoteKeyboardCommand.Operation.KEY_UP,29)).single().outcome)
        assertEquals(listOf(6,6,8,0),sent.map{it.action})
        assertEquals(b,arbiter.heldParticipant);assertFalse(arbiter.fenced)
    }
    @Test fun `same client may hold a key and drag while peer close releases only its keyboard`() = runBlocking {
        val sent=mutableListOf<SharedPointerArbiter.NativeAction>();val a="participant_A_1234"
        val arbiter=SharedPointerArbiter(960,540,{1000}){sent+=it;true};arbiter.attach(a,5000,true)
        arbiter.offer(SharedPointerArbiter.Event(a,1,1,0,10,20,1000))
        arbiter.offer(SharedPointerArbiter.Event(a,2,0,9,0,0,1000,RemoteKeyboardCommand(RemoteKeyboardCommand.Operation.KEY_DOWN,0,keyCode=51)))
        assertEquals(listOf(0,6),sent.map{it.action});assertEquals(a,arbiter.heldParticipant)
        arbiter.remove(a);assertEquals(listOf(0,6,8,3),sent.map{it.action});assertFalse(arbiter.fenced)
    }
    @Test fun `unknown native key release cannot grant replacement input`() = runBlocking {
        val sent=mutableListOf<SharedPointerArbiter.NativeAction>();val a="participant_A_1234";val b="participant_B_1234"
        val arbiter=SharedPointerArbiter(960,540,{1000}){sent+=it;it.action!=8};arbiter.attach(a,5000,true);arbiter.attach(b,5000,true)
        arbiter.offer(SharedPointerArbiter.Event(a,1,0,9,0,0,1000,RemoteKeyboardCommand(RemoteKeyboardCommand.Operation.KEY_DOWN,0,keyCode=51)))
        assertTrue(arbiter.offer(SharedPointerArbiter.Event(b,1,1,0,10,20,1000)).all{it.outcome==SharedPointerArbiter.Outcome.UNKNOWN})
        assertEquals(listOf(6,8),sent.map{it.action});assertTrue(arbiter.fenced)
    }
}
