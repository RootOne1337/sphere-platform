package com.sphereplatform.audit;
import android.graphics.PixelFormat;
import android.media.Image;
import android.media.ImageReader;
import android.opengl.*;
import java.nio.ByteBuffer;
import org.webrtc.YuvHelper;
public final class NativeYuvGpuBench {
 static ByteBuffer plane(ByteBuffer b,int at,int n){ByteBuffer c=b.duplicate();c.position(at);c.limit(at+n);return c.slice();}
 static void convert(ByteBuffer src,int stride,ByteBuffer out,int w,int h){int y=w*h,c=y/4;YuvHelper.ABGRToI420(src,stride,plane(out,0,y),w,plane(out,y,c),w/2,plane(out,y+c,c),w/2,w,h);}
 static double ms(long n){return (System.nanoTime()-n)/1e6;}
 public static void main(String[] a)throws Exception{
  System.load(a[0]);final int w=1920,h=1080;
  ImageReader reader=ImageReader.newInstance(w,h,PixelFormat.RGBA_8888,2);
  EGLDisplay d=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);int[] v=new int[2];
  if(!EGL14.eglInitialize(d,v,0,v,1))throw new IllegalStateException("egl_init");
  EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
  int[] attrs={EGL14.EGL_RED_SIZE,8,EGL14.EGL_GREEN_SIZE,8,EGL14.EGL_BLUE_SIZE,8,EGL14.EGL_ALPHA_SIZE,8,EGL14.EGL_RENDERABLE_TYPE,EGL14.EGL_OPENGL_ES2_BIT,EGL14.EGL_NONE};
  if(!EGL14.eglChooseConfig(d,attrs,0,configs,0,1,count,0)||count[0]<1)throw new IllegalStateException("egl_config");
  EGLContext ctx=EGL14.eglCreateContext(d,configs[0],EGL14.EGL_NO_CONTEXT,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,2,EGL14.EGL_NONE},0);
  EGLSurface surface=EGL14.eglCreateWindowSurface(d,configs[0],reader.getSurface(),new int[]{EGL14.EGL_NONE},0);
  if(!EGL14.eglMakeCurrent(d,surface,surface,ctx))throw new IllegalStateException("egl_current");
  Image image=null;
  try{
   GLES20.glViewport(0,0,w,h);GLES20.glClearColor(90/255f,140/255f,180/255f,1);GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
   if(!EGL14.eglSwapBuffers(d,surface))throw new IllegalStateException("egl_swap");
   long until=System.nanoTime()+500000000L;
   while(image==null&&System.nanoTime()<until){image=reader.acquireLatestImage();if(image==null)Thread.sleep(5);}
   if(image==null)throw new IllegalStateException("no_image");
   Image.Plane p=image.getPlanes()[0];ByteBuffer source=p.getBuffer();int stride=p.getRowStride(),pixel=p.getPixelStride();
   if(pixel!=4)throw new IllegalStateException("pixel_stride");
   int needed=(h-1)*stride+w*4;
   ByteBuffer owned=ByteBuffer.allocateDirect(needed),out=ByteBuffer.allocateDirect(w*h*3/2);byte[] heap=new byte[needed];
   System.out.println("source_direct="+source.isDirect()+" stride="+stride+" pixel="+pixel+" bytes="+needed);
   for(int i=0;i<4;i++){
    long t=System.nanoTime();convert(source,stride,out,w,h);double direct=ms(t);
    ByteBuffer view=source.duplicate();view.position(0);view.limit(needed);owned.clear();
    t=System.nanoTime();owned.put(view);double copy=ms(t);owned.clear();
    t=System.nanoTime();convert(owned,stride,out,w,h);double staged=ms(t);
    view=source.duplicate();view.position(0);view.limit(needed);t=System.nanoTime();view.get(heap);double get=ms(t);
    owned.clear();t=System.nanoTime();owned.put(heap);double put=ms(t);owned.clear();
    t=System.nanoTime();convert(owned,stride,out,w,h);double viaheap=ms(t);
    System.out.println("iteration="+i+" direct_ms="+direct+" direct_copy_ms="+copy+" staged_ms="+staged+" heap_get_ms="+get+" heap_put_ms="+put+" heap_staged_ms="+viaheap+" y="+(out.get(0)&255));
   }
  }finally{
   if(image!=null)image.close();
   EGL14.eglMakeCurrent(d,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
   EGL14.eglDestroySurface(d,surface);EGL14.eglDestroyContext(d,ctx);EGL14.eglTerminate(d);reader.close();
  }
 }
}
