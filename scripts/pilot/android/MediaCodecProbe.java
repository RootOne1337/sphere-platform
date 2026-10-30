package com.sphereplatform.audit;

import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLExt;
import android.opengl.EGLSurface;
import android.opengl.GLES20;
import android.os.Handler;
import android.os.HandlerThread;
import android.view.Surface;
import java.util.ArrayList;
import java.nio.ByteBuffer;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Finite, standalone app_process diagnostic. Never bundled in the agent APK.
 * No display capture, input, network, account data or persistent settings.
 * Benchmarks synthetic Surface / planar input; NOT end-to-end stream acceptance.
 */
public final class MediaCodecProbe {
    private static final int WIDTH = 960, HEIGHT = 540, FPS = 30, BITRATE = 1500000;
    private static final long WARMUP_NS = 150000000L, MEASURE_NS = 1200000000L;
    private static final String AVC = MediaFormat.MIMETYPE_VIDEO_AVC;
    private static final String VP8 = MediaFormat.MIMETYPE_VIDEO_VP8;
    private static final String VP9 = MediaFormat.MIMETYPE_VIDEO_VP9;

    private static JSONObject inventory() throws Exception {
        JSONArray entries = new JSONArray();
        for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos()) {
            if (!info.isEncoder()) continue;
            for (String type : info.getSupportedTypes()) {
                if (!type.equals(AVC) && !type.equals(VP8) && !type.equals(VP9)) continue;
                JSONObject item = new JSONObject().put("name", info.getName()).put("mime", type);
                try {
                    MediaCodecInfo.CodecCapabilities caps = info.getCapabilitiesForType(type);
                    MediaCodecInfo.EncoderCapabilities encoder = caps.getEncoderCapabilities();
                    JSONArray colors = new JSONArray(), profiles = new JSONArray();
                    for (int color : caps.colorFormats) colors.put(color);
                    for (MediaCodecInfo.CodecProfileLevel profile : caps.profileLevels) {
                        profiles.put(new JSONObject().put("profile", profile.profile).put("level", profile.level));
                    }
                    item.put("colors", colors).put("profiles", profiles)
                        .put("size_rate_supported", caps.getVideoCapabilities().areSizeAndRateSupported(WIDTH, HEIGHT, FPS))
                        .put("cbr", encoder.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR))
                        .put("vbr", encoder.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_VBR))
                        .put("complexity_min", encoder.getComplexityRange().getLower())
                        .put("complexity_max", encoder.getComplexityRange().getUpper())
                        .put("max_instances", caps.getMaxSupportedInstances());
                } catch (Exception error) { item.put("error", error.toString()); }
                entries.put(item);
            }
        }
        return new JSONObject().put("mode", "inventory").put("api", android.os.Build.VERSION.SDK_INT)
            .put("width", WIDTH).put("height", HEIGHT).put("fps", FPS).put("encoders", entries);
    }

    private static final class Collector {
        final ArrayList<Long> pts = new ArrayList<>(), received = new ArrayList<>();
        final ArrayList<Integer> sizes = new ArrayList<>();
        String error;
        synchronized void add(MediaCodec.BufferInfo info) {
            if (info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0 && pts.size() < 128) {
                pts.add(info.presentationTimeUs); received.add(System.nanoTime()); sizes.add(info.size);
            }
        }
        synchronized void fail(String message) { error = message; }
        synchronized int count(long start, long end) {
            int count = 0;
            for (long value : pts) if (value * 1000L >= start && value * 1000L < end) count++;
            return count;
        }
    }

    private static JSONObject finish(Collector output, JSONObject result, long start, long end, int submitted) throws Exception {
        long drainStart = System.nanoTime(), drainDeadline = drainStart + 1000000000L;
        while (output.count(start, end) < submitted && System.nanoTime() < drainDeadline) Thread.sleep(10);
        JSONArray ages = new JSONArray();
        int pictures = 0, bytes = 0;
        synchronized (output) {
            for (int i = 0; i < output.pts.size(); i++) {
                long pts = output.pts.get(i) * 1000L;
                if (pts >= start && pts < end) {
                    pictures++; bytes += output.sizes.get(i); ages.put((output.received.get(i) - pts) / 1000000.0);
                }
            }
            result.put("error", output.error == null ? JSONObject.NULL : output.error);
        }
        return result.put("pictures", pictures).put("picture_fps", pictures / (MEASURE_NS / 1000000000.0))
            .put("encoded_bytes", bytes).put("encode_age_ms", ages).put("submitted", submitted)
            .put("inflight_at_drain_deadline", submitted - pictures).put("drain_ms", (System.nanoTime() - drainStart) / 1000000.0)
            .put("scope", "synthetic_encoder_input_only");
    }

    private static JSONObject benchmark(String name, String bitrateMode) throws Exception {
        // Only advertised video encoders are admitted; there is no arbitrary reflection or shell dispatch.
        MediaCodecInfo selected = null;
        for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos()) {
            if (info.isEncoder() && info.getName().equals(name)) selected = info;
        }
        if (selected == null) throw new IllegalArgumentException("unknown_encoder");
        String mime = null;
        for (String type : selected.getSupportedTypes()) {
            if (type.equals(AVC) || type.equals(VP8)) { mime = type; break; }
        }
        if (mime == null) throw new IllegalArgumentException("only_avc_or_vp8_benchmark");
        MediaCodecInfo.EncoderCapabilities capabilities = selected.getCapabilitiesForType(mime).getEncoderCapabilities();
        int requestedMode;
        if (bitrateMode.equals("cbr")) requestedMode = MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR;
        else if (bitrateMode.equals("vbr")) requestedMode = MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_VBR;
        else throw new IllegalArgumentException("cbr_or_vbr_required");
        // CBR is deliberately admitted even if unadvertised: it reproduces the
        // currently requested agent format. Acceptance or rejection is evidence.
        boolean advertised = capabilities.isBitrateModeSupported(requestedMode);
        MediaCodec codec = null;
        Surface input = null;
        EGLDisplay display = EGL14.EGL_NO_DISPLAY;
        EGLContext context = EGL14.EGL_NO_CONTEXT;
        EGLSurface eglSurface = EGL14.EGL_NO_SURFACE;
        HandlerThread callbacks = new HandlerThread("sphere-codec-probe");
        Collector output = new Collector();
        ArrayList<Double> swaps = new ArrayList<>();
        long start = 0, end = 0;
        int submitted = 0;
        boolean started = false;
        try {
            callbacks.start();
            codec = MediaCodec.createByCodecName(name);
            codec.setCallback(new MediaCodec.Callback() {
                @Override public void onInputBufferAvailable(MediaCodec c, int index) { }
                @Override public void onOutputBufferAvailable(MediaCodec c, int index, MediaCodec.BufferInfo info) {
                    try { output.add(info); }
                    finally { try { c.releaseOutputBuffer(index, false); } catch (IllegalStateException ignored) { } }
                }
                @Override public void onError(MediaCodec c, MediaCodec.CodecException error) { output.fail(error.toString()); }
                @Override public void onOutputFormatChanged(MediaCodec c, MediaFormat format) { }
            }, new Handler(callbacks.getLooper()));
            MediaFormat format = MediaFormat.createVideoFormat(mime, WIDTH, HEIGHT);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
            format.setInteger(MediaFormat.KEY_BIT_RATE, BITRATE);
            format.setInteger(MediaFormat.KEY_FRAME_RATE, FPS);
            format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
            format.setInteger(MediaFormat.KEY_BITRATE_MODE, requestedMode);
            format.setInteger(MediaFormat.KEY_PRIORITY, 0);
            if (mime.equals(AVC)) {
                format.setInteger(MediaFormat.KEY_PROFILE, MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline);
                format.setInteger(MediaFormat.KEY_LEVEL, MediaCodecInfo.CodecProfileLevel.AVCLevel31);
            }
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            input = codec.createInputSurface();
            display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
            int[] version = new int[2];
            if (!EGL14.eglInitialize(display, version, 0, version, 1)) throw new IllegalStateException("egl_initialize");
            EGLConfig[] configs = new EGLConfig[1];
            int[] count = new int[1];
            int[] attributes = {EGL14.EGL_RED_SIZE, 8, EGL14.EGL_GREEN_SIZE, 8, EGL14.EGL_BLUE_SIZE, 8,
                EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT, 0x3142, 1, EGL14.EGL_NONE};
            if (!EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0) || count[0] < 1) {
                throw new IllegalStateException("egl_config");
            }
            context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE}, 0);
            eglSurface = EGL14.eglCreateWindowSurface(display, configs[0], input, new int[]{EGL14.EGL_NONE}, 0);
            if (!EGL14.eglMakeCurrent(display, eglSurface, eglSurface, context)) throw new IllegalStateException("egl_current");
            GLES20.glViewport(0, 0, WIDTH, HEIGHT);
            codec.start(); started = true;
            long warmup = System.nanoTime(), deadline = warmup + WARMUP_NS + MEASURE_NS;
            start = warmup + WARMUP_NS;
            long next = warmup;
            for (int sequence = 0; System.nanoTime() < deadline && sequence < 128; sequence++) {
                long now = System.nanoTime();
                if (now < next) { long delay = next - now; Thread.sleep(delay / 1000000L, (int)(delay % 1000000L)); }
                now = System.nanoTime();
                if (now >= deadline) break;
                // Identical spatial detail and motion for every codec; no real screen content.
                GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
                GLES20.glClearColor(.12f, .16f, .2f, 1); GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
                GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
                for (int stripe = 0; stripe < 24; stripe++) {
                    GLES20.glScissor(stripe * 40, 0, 20, HEIGHT);
                    GLES20.glClearColor(.25f, .55f, .75f, 1); GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
                }
                GLES20.glScissor((sequence * 23) % (WIDTH - 80), (sequence * 11) % (HEIGHT - 80), 80, 80);
                GLES20.glClearColor(.95f, .7f, .2f, 1); GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
                EGLExt.eglPresentationTimeANDROID(display, eglSurface, now);
                long swapStart = System.nanoTime();
                if (!EGL14.eglSwapBuffers(display, eglSurface)) throw new IllegalStateException("egl_swap");
                if (now >= start) { submitted++; swaps.add((System.nanoTime() - swapStart) / 1000000.0); }
                next = Math.max(next + 1000000000L / FPS, System.nanoTime());
            }
            end = deadline;
            JSONObject result = new JSONObject().put("mode", "bench").put("encoder", name).put("mime", mime)
                .put("width", WIDTH).put("height", HEIGHT).put("target_fps", FPS).put("bitrate", BITRATE)
                .put("bitrate_mode", bitrateMode).put("bitrate_mode_advertised", advertised)
                .put("measurement_ms", MEASURE_NS / 1000000)
                .put("input", "surface").put("swap_ms", new JSONArray(swaps));
            return finish(output, result, start, end, submitted);
        } finally {
            if (display != EGL14.EGL_NO_DISPLAY) {
                EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
                if (eglSurface != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, eglSurface);
                if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context);
                EGL14.eglTerminate(display);
            }
            if (codec != null) { try { if (started) codec.stop(); } finally { codec.release(); } }
            if (input != null) input.release();
            callbacks.quitSafely(); callbacks.join(300);
        }
    }

    private static JSONObject benchmarkPlanar(String name) throws Exception {
        if (!name.equals("OMX.google.h264.encoder") && !name.equals("OMX.google.vp8.encoder")) {
            throw new IllegalArgumentException("planar_probe_requires_known_google_encoder");
        }
        String mime = name.equals("OMX.google.h264.encoder") ? AVC : VP8;
        MediaCodec codec = null;
        boolean started = false;
        HandlerThread callbacks = new HandlerThread("sphere-codec-probe");
        Collector output = new Collector();
        final ArrayBlockingQueue<Integer> available = new ArrayBlockingQueue<>(64);
        int submitted = 0;
        ArrayList<Double> inputWait = new ArrayList<>(), fills = new ArrayList<>();
        try {
            callbacks.start(); codec = MediaCodec.createByCodecName(name);
            codec.setCallback(new MediaCodec.Callback() {
                @Override public void onInputBufferAvailable(MediaCodec c, int index) { available.offer(index); }
                @Override public void onOutputBufferAvailable(MediaCodec c, int index, MediaCodec.BufferInfo info) {
                    try { output.add(info); }
                    finally { try { c.releaseOutputBuffer(index, false); } catch (IllegalStateException ignored) { } }
                }
                @Override public void onError(MediaCodec c, MediaCodec.CodecException error) { output.fail(error.toString()); }
                @Override public void onOutputFormatChanged(MediaCodec c, MediaFormat format) { }
            }, new Handler(callbacks.getLooper()));
            MediaFormat format = MediaFormat.createVideoFormat(mime, WIDTH, HEIGHT);
            format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Planar);
            format.setInteger(MediaFormat.KEY_BIT_RATE, BITRATE); format.setInteger(MediaFormat.KEY_FRAME_RATE, FPS);
            format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1); format.setInteger(MediaFormat.KEY_PRIORITY, 0);
            format.setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR);
            if (mime.equals(AVC)) {
                format.setInteger(MediaFormat.KEY_PROFILE, MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline);
                format.setInteger(MediaFormat.KEY_LEVEL, MediaCodecInfo.CodecProfileLevel.AVCLevel31);
            }
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            byte[] background = new byte[WIDTH * HEIGHT * 3 / 2];
            int ySize = WIDTH * HEIGHT, cSize = ySize / 4;
            for (int y = 0; y < HEIGHT; y++) for (int x = 0; x < WIDTH; x++) {
                background[y * WIDTH + x] = (byte)(x % 40 < 20 ? 122 : 49);
            }
            for (int y = 0; y < HEIGHT / 2; y++) for (int x = 0; x < WIDTH / 2; x++) {
                int index = y * (WIDTH / 2) + x;
                background[ySize + index] = (byte)(x % 20 < 10 ? 162 : 134);
                background[ySize + cSize + index] = (byte)(x % 20 < 10 ? 92 : 122);
            }
            byte[] picture = new byte[background.length];
            codec.start(); started = true;
            long warmup = System.nanoTime(), start = warmup + WARMUP_NS, end = start + MEASURE_NS, next = warmup;
            for (int sequence = 0; System.nanoTime() < end && sequence < 128; sequence++) {
                long now = System.nanoTime();
                if (now < next) { long delay = next - now; Thread.sleep(delay / 1000000L, (int)(delay % 1000000L)); }
                long waitStart = System.nanoTime();
                Integer index = available.poll(50, TimeUnit.MILLISECONDS);
                if (index == null) continue;
                long fillStart = System.nanoTime();
                if (fillStart >= end) break;
                System.arraycopy(background, 0, picture, 0, picture.length);
                int left = (sequence * 23) % (WIDTH - 80), top = (sequence * 11) % (HEIGHT - 80);
                for (int y = top; y < top + 80; y++) java.util.Arrays.fill(picture, y * WIDTH + left, y * WIDTH + left + 80, (byte)175);
                for (int y = top / 2; y < top / 2 + 40; y++) {
                    int offset = y * (WIDTH / 2) + left / 2;
                    java.util.Arrays.fill(picture, ySize + offset, ySize + offset + 40, (byte)62);
                    java.util.Arrays.fill(picture, ySize + cSize + offset, ySize + cSize + offset + 40, (byte)165);
                }
                ByteBuffer buffer = codec.getInputBuffer(index);
                if (buffer == null || buffer.capacity() < picture.length) throw new IllegalStateException("planar_buffer_capacity");
                buffer.clear(); buffer.put(picture);
                long pts = System.nanoTime();
                if (pts >= end) break;
                codec.queueInputBuffer(index, 0, picture.length, pts / 1000L, 0);
                if (pts >= start) {
                    submitted++; inputWait.add((fillStart - waitStart) / 1000000.0); fills.add((pts - fillStart) / 1000000.0);
                }
                next = Math.max(next + 1000000000L / FPS, System.nanoTime());
            }
            JSONObject result = new JSONObject().put("mode", "bench-planar").put("encoder", name).put("mime", mime)
                .put("width", WIDTH).put("height", HEIGHT).put("target_fps", FPS).put("bitrate", BITRATE)
                .put("bitrate_mode", "cbr").put("input", "yuv420_planar").put("measurement_ms", MEASURE_NS / 1000000)
                .put("input_wait_ms", new JSONArray(inputWait)).put("fill_ms", new JSONArray(fills));
            return finish(output, result, start, end, submitted);
        } finally {
            if (codec != null) { try { if (started) codec.stop(); } finally { codec.release(); } }
            callbacks.quitSafely(); callbacks.join(300);
        }
    }

    public static void main(String[] args) {
        int exit = 1;
        try {
            // app_process has no Zygote-prepared main Looper. API 28's MediaCodec
            // constructor needs one even when callbacks use an explicit thread.
            if (android.os.Looper.myLooper() == null) android.os.Looper.prepareMainLooper();
            JSONObject result;
            if (args.length == 1 && args[0].equals("inventory")) result = inventory();
            else if (args.length == 3 && args[0].equals("bench")) {
                result = benchmark(args[1], args[2]);
            } else if (args.length == 2 && args[0].equals("bench-planar")) {
                result = benchmarkPlanar(args[1]);
            } else throw new IllegalArgumentException("inventory_or_bench_encoder_required");
            System.out.println(result.toString()); exit = 0;
        } catch (Exception error) {
            try {
                System.out.println(new JSONObject().put("status", "error").put("error", error.toString()).toString());
                // The diagnostic completed; consumers must inspect the JSON error.
                exit = 0;
            } catch (Exception serializationError) { System.out.println("{\"status\":\"error\"}"); }
        }
        System.exit(exit);
    }
}
