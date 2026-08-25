/*{
 "TITLE":"Matrix / Code Rain","DESCRIPTION":"Low-resolution falling digital columns using bright LED blocks rather than unreadably tiny glyphs.","CREDIT":"Pi Matrix Signage","CATEGORIES":["Built-in","Digital","Generator"],
 "INPUTS":[
  {"NAME":"Speed","LABEL":"Speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":4.0},
  {"NAME":"Density","LABEL":"Density","TYPE":"float","DEFAULT":0.7,"MIN":0.05,"MAX":1.0},
  {"NAME":"Trail","LABEL":"Trail length","TYPE":"float","DEFAULT":0.55,"MIN":0.1,"MAX":1.0},
  {"NAME":"HeadColor","LABEL":"Head colour","TYPE":"color","DEFAULT":[0.85,1.0,0.85,1.0]},
  {"NAME":"TrailColor","LABEL":"Trail colour","TYPE":"color","DEFAULT":[0.0,0.8,0.18,1.0]},
  {"NAME":"Background","LABEL":"Background","TYPE":"color","DEFAULT":[0.0,0.01,0.0,1.0]}
 ],"ISFVSN":"2"
}*/
float hh(float n){return fract(sin(n*91.17)*43758.5453);}
void main(){vec2 p=gl_FragCoord.xy;float col=floor(p.x/3.0);float seed=hh(col);float rate=5.0+seed*10.0;float head=mod(TIME*Speed*rate+seed*RENDERSIZE.y,RENDERSIZE.y+14.0)-7.0;float d=head-p.y;float trail=max(3.0,Trail*RENDERSIZE.y*.7);float a=step(0.0,d)*(1.0-smoothstep(0.0,trail,d))*step(1.0-Density,hh(col+4.0));float block=step(.2,fract(p.y/3.0))*step(fract(p.y/3.0),.82);a*=block;float h=1.0-smoothstep(0.0,2.2,abs(d));vec3 c=mix(TrailColor.rgb,HeadColor.rgb,h);gl_FragColor=vec4(mix(Background.rgb,c,a),1.0);}
