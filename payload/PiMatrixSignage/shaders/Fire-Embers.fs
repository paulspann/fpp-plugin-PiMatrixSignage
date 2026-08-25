/*{
  "TITLE":"Fire & Embers",
  "DESCRIPTION":"Low-resolution flames, heat glow and rising embers designed for P5/P10 LED matrices.",
  "CREDIT":"Pi Matrix Signage",
  "CATEGORIES":["Built-in","Fire","Generator"],
  "INPUTS":[
    {"NAME":"Style","LABEL":"Style","TYPE":"long","DEFAULT":0,"VALUES":[0,1,2],"LABELS":["Camp fire","Hot embers","Magic flame"]},
    {"NAME":"Speed","LABEL":"Speed","TYPE":"float","DEFAULT":1.0,"MIN":0.1,"MAX":4.0},
    {"NAME":"FlameHeight","LABEL":"Flame height","TYPE":"float","DEFAULT":0.72,"MIN":0.15,"MAX":1.0},
    {"NAME":"Turbulence","LABEL":"Turbulence","TYPE":"float","DEFAULT":0.55,"MIN":0.0,"MAX":1.0},
    {"NAME":"Sparks","LABEL":"Embers / sparks","TYPE":"float","DEFAULT":0.45,"MIN":0.0,"MAX":1.0},
    {"NAME":"HotColor","LABEL":"Hot colour","TYPE":"color","DEFAULT":[1.0,0.92,0.35,1.0]},
    {"NAME":"FlameColor","LABEL":"Flame colour","TYPE":"color","DEFAULT":[1.0,0.22,0.02,1.0]},
    {"NAME":"DeepColor","LABEL":"Deep colour","TYPE":"color","DEFAULT":[0.32,0.01,0.0,1.0]},
    {"NAME":"Opacity","LABEL":"Opacity","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":1.0}
  ],"ISFVSN":"2"
}*/
float h1(float n){return fract(sin(n*127.1)*43758.5453);}
float noise2(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);float a=h1(i.x+i.y*157.0),b=h1(i.x+1.0+i.y*157.0),c=h1(i.x+(i.y+1.0)*157.0),d=h1(i.x+1.0+(i.y+1.0)*157.0);return mix(mix(a,b,f.x),mix(c,d,f.x),f.y);}
void main(){
  vec2 p=gl_FragCoord.xy; vec2 uv=p/max(RENDERSIZE,vec2(1.0)); float t=TIME*Speed;
  float y=uv.y/max(FlameHeight,.01); float n=noise2(vec2(uv.x*7.0 + sin(t*.7), uv.y*8.0-t*2.0));
  n=.62*n+.38*noise2(vec2(uv.x*15.0-t*.4,uv.y*13.0-t*3.1));
  float sway=sin(uv.x*17.0+t*2.3)*.055*Turbulence + (n-.5)*.22*Turbulence;
  float body=clamp(1.0-y+sway,0.0,1.0); body=smoothstep(.02,.82,body);
  if(Style==1) body*=.48; else if(Style==2) body=pow(body,.78);
  float heat=clamp(body*1.35,0.0,1.0);
  vec3 col=mix(DeepColor.rgb,FlameColor.rgb,smoothstep(.05,.65,heat)); col=mix(col,HotColor.rgb,smoothstep(.58,1.0,heat));
  float spark=0.0; if(Sparks>0.0){float cell=floor(p.x)+floor((p.y+t*12.0)/3.0)*311.0;float r=h1(cell);float drift=fract((p.y+t*(8.0+12.0*h1(cell+3.0)))/max(RENDERSIZE.y,1.0));spark=step(1.0-Sparks*.065,r)*step(.18,uv.y)*step(drift,.72);}
  col=mix(col,HotColor.rgb,spark); float a=max(body,spark*.9)*Opacity;
  gl_FragColor=vec4(col,clamp(a,0.0,1.0));
}
