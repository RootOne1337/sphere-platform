package com.sphereplatform.audit;
import android.graphics.Matrix;
import android.opengl.GLES20;
import android.os.Handler;
import android.os.HandlerThread;
import java.nio.ByteBuffer;
import org.webrtc.*;
public final class GpuYuvConverterBench{
 public static void main(String[] a)throws Exception{
  System.load(a[0]); final int w=1920,h=1080;
  EglBase egl=EglBase.create(null,EglBase.CONFIG_PIXEL_BUFFER);egl.createDummyPbufferSurface();egl.makeCurrent();
  HandlerThread thread=new HandlerThread("sphere-standalone-bench");thread.start();
  YuvConverter converter=new YuvConverter();TextureBufferImpl texture=null;
  int[] tex=new int[1];GLES20.glGenTextures(1,tex,0);GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,tex[0]);
  GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_MIN_FILTER,GLES20.GL_LINEAR);GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_MAG_FILTER,GLES20.GL_LINEAR);
  ByteBuffer rgba=ByteBuffer.allocateDirect(w*h*4);
  for(int i=0;i<w*h;i++){rgba.put((byte)90);rgba.put((byte)140);rgba.put((byte)180);rgba.put((byte)255);}rgba.clear();
  GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D,0,GLES20.GL_RGBA,w,h,0,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,rgba);
  if(GLES20.glGetError()!=GLES20.GL_NO_ERROR)throw new IllegalStateException("texture_upload");
  try{
   texture=new TextureBufferImpl(w,h,VideoFrame.TextureBuffer.Type.RGB,tex[0],new Matrix(),new Handler(thread.getLooper()),converter,new Runnable(){public void run(){}});
   for(int i=0;i<5;i++){
    long start=System.nanoTime();VideoFrame.I420Buffer yuv=converter.convert(texture);double ms=(System.nanoTime()-start)/1e6;
    if(yuv==null)throw new IllegalStateException("null_yuv");
    try{System.out.println("gpu_yuv iteration="+i+" ms="+ms+" width="+yuv.getWidth()+" height="+yuv.getHeight()+" strideY="+yuv.getStrideY()+" y="+(yuv.getDataY().get(0)&255)+" u="+(yuv.getDataU().get(0)&255)+" v="+(yuv.getDataV().get(0)&255));}finally{yuv.release();}
   }
  }finally{if(texture!=null)texture.release();converter.release();GLES20.glDeleteTextures(1,tex,0);egl.release();thread.quitSafely();thread.join(100);}
 }
}
