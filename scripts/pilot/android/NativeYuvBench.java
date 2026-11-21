package com.sphereplatform.audit;
import java.nio.ByteBuffer;
import org.webrtc.YuvHelper;
public final class NativeYuvBench {
 public static void main(String[] args) {
  System.load(args[0]);
  final int w=1920,h=1080,y=w*h,c=y/4;
  ByteBuffer src=ByteBuffer.allocateDirect(w*h*4),out=ByteBuffer.allocateDirect(y+2*c);
  for(int i=0;i<w*h;i++){src.put((byte)90);src.put((byte)140);src.put((byte)180);src.put((byte)255);} src.clear();
  ByteBuffer u=out.duplicate();u.position(y);u.limit(y+c);u=u.slice();
  ByteBuffer v=out.duplicate();v.position(y+c);v.limit(y+2*c);v=v.slice();
  ByteBuffer yy=out.duplicate();yy.limit(y);yy=yy.slice();
  for(int i=0;i<7;i++){
   long start=System.nanoTime();
   YuvHelper.ABGRToI420(src,w*4,yy,w,u,w/2,v,w/2,w,h);
   double ms=(System.nanoTime()-start)/1e6;
   System.out.println("owned_direct iteration="+i+" ms="+ms+" y="+(out.get(0)&255)+" u="+(out.get(y)&255)+" v="+(out.get(y+c)&255));
  }
 }
}
