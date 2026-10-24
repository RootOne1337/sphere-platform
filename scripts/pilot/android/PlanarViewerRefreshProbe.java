package com.sphereplatform.audit;

import android.os.Handler;
import android.os.HandlerThread;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.ByteBuffer;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Bounded app_process probe of the APK's actual MediaCodec, without screen capture.
 * Supply the APK and this dex JAR in CLASSPATH. Submits exactly one synthetic RAW
 * image, then requests two IDRs with no producer activity. Prints counters only.
 * Never installs the APK, requests Android permissions, or writes image bytes.
 */
public final class PlanarViewerRefreshProbe {
    private static Method method(Class<?> type, String prefix) {
        for (Method m : type.getDeclaredMethods()) {
            if (m.getName().equals(prefix) || m.getName().startsWith(prefix + "$")) {
                m.setAccessible(true); return m;
            }
        }
        throw new IllegalStateException("Missing probe method " + prefix);
    }
    public static void main(String[] args) throws Exception {
        final HandlerThread thread = new HandlerThread("sphere-planar-refresh-probe");
        final AtomicReference<Object> encoder = new AtomicReference<>();
        final AtomicReference<Throwable> failure = new AtomicReference<>();
        final AtomicInteger pictures = new AtomicInteger();
        final AtomicInteger idrs = new AtomicInteger();
        final AtomicInteger errors = new AtomicInteger();
        final Class<?> type = Class.forName("com.sphereplatform.agent.streaming.H264Encoder");
        final Class<?> function0 = Class.forName("kotlin.jvm.functions.Function0");
        final Class<?> function1 = Class.forName("kotlin.jvm.functions.Function1");
        final Class<?> function2 = Class.forName("kotlin.jvm.functions.Function2");
        final Object unit = Class.forName("kotlin.Unit").getField("INSTANCE").get(null);
        final ClassLoader loader = type.getClassLoader();
        final Object clock = Proxy.newProxyInstance(loader, new Class<?>[]{function0},
            (p, m, a) -> m.getName().equals("invoke") ? Long.valueOf(System.nanoTime()) : null);
        final Object onFrame = Proxy.newProxyInstance(loader, new Class<?>[]{function2}, (p, m, a) -> {
            if (m.getName().equals("invoke")) {
                Object metadata = a[1];
                if (!((Boolean) method(metadata.getClass(), "isCodecConfig").invoke(metadata))) {
                    pictures.incrementAndGet();
                    if ((Boolean) method(metadata.getClass(), "isKeyFrame").invoke(metadata)) idrs.incrementAndGet();
                }
                return unit;
            }
            return null;
        });
        final Object onError = Proxy.newProxyInstance(loader, new Class<?>[]{function1}, (p, m, a) -> {
            if (m.getName().equals("invoke")) { errors.incrementAndGet(); failure.compareAndSet(null, (Throwable) a[0]); return unit; }
            return null;
        });
        final Class<?> configType = Class.forName(type.getName() + "$EncoderConfig");
        final Object config = configType.getConstructor(int.class,int.class,int.class,int.class,int.class)
            .newInstance(960,540,30,1500000,1);
        final Method start = method(type, "startPlanar");
        final Method submit = method(type, "submitPlanarFrame");
        final Method request = method(type, "requestKeyFrame");
        final Method stop = method(type, "stop");
        final ByteBuffer raw = ByteBuffer.allocate(960 * 540 * 4);
        for (int y=0;y<540;y++) for (int x=0;x<960;x++)
            raw.put((byte)(x%256)).put((byte)(y%256)).put((byte)64).put((byte)255);
        raw.rewind();
        thread.start();
        final Handler handler = new Handler(thread.getLooper());
        try {
            final CountDownLatch ready = new CountDownLatch(1);
            handler.post(() -> {
                try {
                    Object value = null;
                    for (Constructor<?> c : type.getConstructors()) {
                        if (c.getParameterCount()==2) value=c.newInstance(config,onFrame);
                        else if (c.getParameterCount()==3 && c.getParameterTypes()[1]==function0)
                            value=c.newInstance(config,clock,onFrame);
                        if (value!=null) break;
                    }
                    if (value==null) throw new IllegalStateException("Unsupported encoder constructor");
                    encoder.set(value); method(type,"setOnEncoderError").invoke(value,onError);
                    start.invoke(value);
                } catch (Throwable t) { failure.set(t); } finally { ready.countDown(); }
            });
            if (!ready.await(4,TimeUnit.SECONDS) || failure.get()!=null) throw new IllegalStateException("Encoder startup failed", failure.get());
            boolean admitted=false;
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
            while (!admitted && System.nanoTime()<deadline && failure.get()==null) {
                admitted=(Boolean) submit.invoke(encoder.get(),raw,960*4,4,System.nanoTime()/1000);
                if (!admitted) Thread.sleep(20);
            }
            if (!admitted) throw new IllegalStateException("RAW input was not admitted");
            deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
            while(pictures.get()<1 && System.nanoTime()<deadline && failure.get()==null) Thread.sleep(20);
            int initial=pictures.get(), initialIdrs=idrs.get();
            if (initial!=1 || initialIdrs!=1) throw new IllegalStateException("Initial picture missing");
            int[] added=new int[2]; boolean[] accepted=new boolean[2];
            for (int i=0;i<2;i++) {
                Thread.sleep(350);
                int before=pictures.get();
                accepted[i]=(Boolean) request.invoke(encoder.get());
                deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
                while(pictures.get()==before && System.nanoTime()<deadline && failure.get()==null) Thread.sleep(20);
                added[i]=pictures.get()-before;
            }
            System.out.println("{\"sourceRawImages\":1,\"initialPictures\":"+initial+
                ",\"refreshAccepted\":["+accepted[0]+","+accepted[1]+"],\"refreshPictures\":["+added[0]+","+added[1]+
                "],\"totalPictures\":"+pictures.get()+",\"totalIdrs\":"+idrs.get()+",\"errors\":"+errors.get()+
                ",\"capturePermissionsRequested\":false,\"pixelsPersisted\":false}");
            if (failure.get()!=null) throw new IllegalStateException("Encoder failed",failure.get());
        } finally {
            final CountDownLatch stopped=new CountDownLatch(1);
            handler.post(() -> { try { if (encoder.get()!=null) stop.invoke(encoder.get()); }
                catch(Throwable t) { failure.compareAndSet(null,t); } finally { stopped.countDown(); } });
            stopped.await(4,TimeUnit.SECONDS); thread.quitSafely(); thread.join(4000);
            if(thread.isAlive()) throw new IllegalStateException("Codec looper did not stop");
            if(failure.get()!=null) throw new IllegalStateException("Native probe cleanup failed",failure.get());
        }
    }
}
