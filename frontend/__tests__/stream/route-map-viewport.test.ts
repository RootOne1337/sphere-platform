import {boundRouteViewport,fittedRouteViewport,inverseRouteDisplayPoint,pickRouteDisplayPoint,routeClientPoint,routeDisplayPoint,zoomRouteViewport} from '@/src/features/stream/routeMapViewport';

test.each([0,Math.PI/2,-Math.PI/2,Math.PI,3.4])('zoom/pan and compass inverse picking round-trip at %s radians',angle=>{
  const points=Object.freeze([{x:135,y:191},{x:341,y:289},{x:498,y:403}]),snapshot=JSON.stringify(points);
  const view={zoom:3.25,panX:-110,panY:75},display=routeDisplayPoint(points[1],view,angle);
  const recovered=inverseRouteDisplayPoint(display,view,angle);
  expect(recovered.x).toBeCloseTo(points[1].x);expect(recovered.y).toBeCloseTo(points[1].y);
  expect(pickRouteDisplayPoint(points,display,view,angle)).toBe(1);
  expect(pickRouteDisplayPoint(points,{x:display.x+15,y:display.y},view,angle)).toBeNull();
  expect(JSON.stringify(points)).toBe(snapshot);
});

test('pointer-anchored zoom preserves the same map location while remaining bounded',()=>{
  const view={zoom:2,panX:35,panY:-60},anchor={x:160,y:220},angle=.72;
  const original=inverseRouteDisplayPoint(anchor,view,angle),next=zoomRouteViewport(view,6,anchor);
  const displayed=routeDisplayPoint(original,next,angle);
  expect(displayed.x).toBeCloseTo(anchor.x);expect(displayed.y).toBeCloseTo(anchor.y);
  expect(zoomRouteViewport(next,1000).zoom).toBe(8);expect(zoomRouteViewport(next,.01).zoom).toBe(1);
  expect(view).toEqual({zoom:2,panX:35,panY:-60});
  expect(boundRouteViewport({zoom:NaN,panX:Infinity,panY:-Infinity})).toEqual(fittedRouteViewport);
  expect(boundRouteViewport({zoom:8,panX:1e10,panY:-1e10})).toEqual({zoom:8,panX:4800,panY:-4320});
});

test('client coordinates respect a letterboxed SVG instead of stretching source picks',()=>{
  const rect={left:20,top:30,width:800,height:540};
  expect(routeClientPoint(rect,{x:120,y:30})).toEqual({x:0,y:0});
  expect(routeClientPoint(rect,{x:720,y:570})).toEqual({x:600,y:540});
  expect(routeClientPoint({...rect,width:0},{x:120,y:30})).toBeNull();
});
