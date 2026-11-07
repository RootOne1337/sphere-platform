/** Presentation coordinates only. Never produces or changes a recovered pose. */
export type MapPoint={x:number;y:number};
export type RouteMapViewport={zoom:number;panX:number;panY:number};
export const fittedRouteViewport:RouteMapViewport={zoom:1,panX:0,panY:0};
const center={x:300,y:270};
export function boundRouteViewport(value:RouteMapViewport):RouteMapViewport {
  const zoom=Math.max(1,Math.min(8,Number.isFinite(value.zoom)?value.zoom:1));
  return {zoom,panX:Math.max(-600*zoom,Math.min(600*zoom,Number.isFinite(value.panX)?value.panX:0)),
    panY:Math.max(-540*zoom,Math.min(540*zoom,Number.isFinite(value.panY)?value.panY:0))};
}
/** Zoom around a pointer in the fixed 600x540 SVG view box. */
export function zoomRouteViewport(view:RouteMapViewport,zoom:number,anchor:MapPoint=center):RouteMapViewport {
  const next=boundRouteViewport({...view,zoom}).zoom;
  return boundRouteViewport({zoom:next,panX:anchor.x-center.x-(anchor.x-center.x-view.panX)*next/view.zoom,
    panY:anchor.y-center.y-(anchor.y-center.y-view.panY)*next/view.zoom});
}
export function routeDisplayPoint(point:MapPoint,view:RouteMapViewport,angle:number):MapPoint {
  const c=Math.cos(angle),s=Math.sin(angle),x=point.x-center.x,y=point.y-center.y;
  return {x:center.x+view.panX+view.zoom*(c*x+s*y),y:center.y+view.panY+view.zoom*(-s*x+c*y)};
}
export function inverseRouteDisplayPoint(point:MapPoint,view:RouteMapViewport,angle:number):MapPoint {
  const c=Math.cos(angle),s=Math.sin(angle),x=(point.x-center.x-view.panX)/view.zoom,y=(point.y-center.y-view.panY)/view.zoom;
  return {x:center.x+c*x-s*y,y:center.y+s*x+c*y};
}
/** Inverse picking uses the same zoom, pan and compass rotation as rendering. */
export function pickRouteDisplayPoint(points:readonly MapPoint[],point:MapPoint,view:RouteMapViewport,angle:number,radius=12):number|null {
  const at=inverseRouteDisplayPoint(point,view,angle);let found:number|null=null,best=(radius/view.zoom)**2;
  points.forEach((p,index)=>{const d=(p.x-at.x)**2+(p.y-at.y)**2;if(d<=best){found=index;best=d;}});
  return found;
}
/** Respect SVG's default xMidYMid meet, including letterboxing. */
export function routeClientPoint(rect:{left:number;top:number;width:number;height:number},point:MapPoint):MapPoint|null {
  const scale=Math.min(rect.width/600,rect.height/540);if(!(scale>0)||!Number.isFinite(scale))return null;
  return {x:(point.x-rect.left-(rect.width-600*scale)/2)/scale,y:(point.y-rect.top-(rect.height-540*scale)/2)/scale};
}
