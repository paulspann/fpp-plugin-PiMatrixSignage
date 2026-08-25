/*{
  "TITLE":"Starfield / Warp Speed","DESCRIPTION":"Low-resolution starfield with optional hyperspace streaking.","CREDIT":"Pi Matrix Signage","CATEGORIES":["Built-in","Space","Generator"],
  "INPUTS":[
    {"NAME":"Mode","LABEL":"Mode","TYPE":"long","DEFAULT":0,"VALUES":[0,1,2],"LABELS":["Drift","Fly through","Warp speed"]},
    {"NAME":"Speed","LABEL":"Speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":6.0},
    {"NAME":"Density","LABEL":"Star density","TYPE":"float","DEFAULT":0.55,"MIN":0.05,"MAX":1.0},
    {"NAME":"StarColor","LABEL":"Star colour","TYPE":"color","DEFAULT":[1.0,1.0,1.0,1.0]},
    {"NAME":"TintColor","LABEL":"Tint colour","TYPE":"color","DEFAULT":[0.35,0.65,1.0,1.0]},
    {"NAME":"Background","LABEL":"Background","TYPE":"color","DEFAULT":[0.0,0.0,0.025,1.0]}
  ],"ISFVSN":"2"
}*/
float hh(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
void main(){
 vec2 p=gl_FragCoord.xy, c=RENDERSIZE*.5, d=p-c; float t=TIME*Speed; vec3 col=Background.rgb;
 if(Mode==0){vec2 q=floor(vec2(p.x-t*7.0,p.y));float r=hh(q);float star=step(1.0-Density*.055,r);float tw=.55+.45*sin(t*4.0+r*29.0);col=mix(col,mix(TintColor.rgb,StarColor.rgb,r),star*tw);}
 else {float ang=atan(d.y,d.x),rad=length(d);float sector=floor((ang+3.14159)*18.0);float lane=floor(rad/3.0);float seed=hh(vec2(sector,lane));float z=fract(seed+t*(Mode==2?.75:.24));float target=rad/(max(RENDERSIZE.x,RENDERSIZE.y)*.72);float delta=abs(z-target);float width=Mode==2?.085:.028;float star=(1.0-smoothstep(width,width*1.8,delta))*step(1.0-Density*.7,seed);if(Mode==2){float streak=1.0-smoothstep(width*3.2,width*8.0,delta);star=max(star,streak*step(1.0-Density*.45,seed)*.55);}col=mix(col,mix(TintColor.rgb,StarColor.rgb,z),clamp(star,0.0,1.0));}
 gl_FragColor=vec4(col,1.0);
}
