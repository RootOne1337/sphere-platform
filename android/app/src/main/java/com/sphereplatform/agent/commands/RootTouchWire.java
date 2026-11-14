package com.sphereplatform.agent.commands;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;

/** Fixed-size big-endian payloads in bounded hex lines; tolerates su/PTY LF to CRLF conversion. */
public final class RootTouchWire {
    public static final int INPUT_MAGIC = 0x53544931, ACK_MAGIC = 0x53544131;
    public static final int INPUT_BYTES = 25, ACK_BYTES = 17;
    public static final int INPUT_LINE_BYTES = INPUT_BYTES * 2 + 1, ACK_LINE_BYTES = ACK_BYTES * 2 + 1;
    private static final byte[] HEX = "0123456789abcdef".getBytes(java.nio.charset.StandardCharsets.US_ASCII);
    public static final class Packet {
        public final int sequence, action, x, y;
        public final long gesture;
        public Packet(int sequence, long gesture, int action, int x, int y) {
            this.sequence = sequence; this.gesture = gesture; this.action = action; this.x = x; this.y = y;
        }
    }
    public static Packet read(InputStream source) throws IOException {
        DataInputStream input = new DataInputStream(new ByteArrayInputStream(readLine(source, INPUT_BYTES)));
        if (input.readInt() != INPUT_MAGIC) throw new IOException("touch_protocol_invalid");
        return new Packet(input.readInt(), input.readLong(), input.readUnsignedByte(), input.readInt(), input.readInt());
    }
    public static void write(OutputStream output, Packet packet) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(INPUT_BYTES);
        DataOutputStream payload = new DataOutputStream(bytes);
        payload.writeInt(INPUT_MAGIC); payload.writeInt(packet.sequence); payload.writeLong(packet.gesture);
        payload.writeByte(packet.action); payload.writeInt(packet.x); payload.writeInt(packet.y);
        writeLine(output, bytes.toByteArray());
    }
    public static void ack(OutputStream output, int sequence, int status, long now) throws IOException {
        synchronized (output) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(ACK_BYTES);
            DataOutputStream payload = new DataOutputStream(bytes);
            payload.writeInt(ACK_MAGIC); payload.writeInt(sequence); payload.writeByte(status); payload.writeLong(now);
            writeLine(output, bytes.toByteArray());
        }
    }
    public static final class Ack {
        public final int sequence, status;
        public final long uptimeMs;
        private Ack(int sequence, int status, long uptimeMs) {
            this.sequence = sequence; this.status = status; this.uptimeMs = uptimeMs;
        }
    }
    public static Ack readAck(InputStream source) throws IOException {
        DataInputStream input = new DataInputStream(new ByteArrayInputStream(readLine(source, ACK_BYTES)));
        if (input.readInt() != ACK_MAGIC) throw new IOException("touch_ack_invalid");
        int sequence = input.readInt(), status = input.readUnsignedByte();
        long uptime = input.readLong();
        if (sequence < 0 || status > 6 || uptime < 0) throw new IOException("touch_ack_invalid");
        return new Ack(sequence, status, uptime);
    }
    private static void writeLine(OutputStream output, byte[] payload) throws IOException {
        byte[] line = new byte[payload.length * 2 + 1];
        for (int i = 0; i < payload.length; i++) {
            line[i * 2] = HEX[(payload[i] & 0xff) >>> 4];
            line[i * 2 + 1] = HEX[payload[i] & 15];
        }
        line[line.length - 1] = '\n';
        output.write(line); output.flush();
    }
    private static byte[] readLine(InputStream input, int size) throws IOException {
        byte[] payload = new byte[size];
        for (int i = 0; i < size; i++) payload[i] = (byte) ((hex(input.read()) << 4) | hex(input.read()));
        int end = input.read();
        if (end == '\r') end = input.read();
        if (end < 0) throw new java.io.EOFException();
        if (end != '\n') throw new IOException("touch_line_invalid");
        return payload;
    }
    private static int hex(int value) throws IOException {
        if (value < 0) throw new java.io.EOFException();
        if (value >= '0' && value <= '9') return value - '0';
        if (value >= 'a' && value <= 'f') return value - 'a' + 10;
        throw new IOException("touch_line_invalid");
    }
    private RootTouchWire() {}
}
