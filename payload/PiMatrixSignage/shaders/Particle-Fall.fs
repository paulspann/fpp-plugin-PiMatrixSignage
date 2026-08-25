/*{
 "TITLE":"Falling Particles","DESCRIPTION":"One low-cost particle shader for snow, confetti, bubbles, stars and hearts.","CREDIT":"Pi Matrix Signage","CATEGORIES":["Built-in","Particles","Generator"],
 "INPUTS":[
  {"NAME":"Style","LABEL":"Particles","TYPE":"long","DEFAULT":0,"VALUES":[0,1,2,3,4],"LABELS":["Snow","Confetti","Bubbles","Stars","Hearts"]},
  {"NAME":"Speed","LABEL":"Fall speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":4.0},
  {"NAME":"Density","LABEL":"Density","TYPE":"float","DEFAULT":0.5,"MIN":0.05,"MAX":1.0},
  {"NAME":"Size","LABEL":"Size","TYPE":"float","DEFAULT":1.4,"MIN":1.0,"MAX":4.0},
  {"NAME":"Wind","LABEL":"Wind","TYPE":"float","DEFAULT":0.15,"MIN":-2.0,"MAX":2.0},
  {"NAME":"ColorA","LABEL":"Colour 1","TYPE":"color","DEFAULT":[1.0,1.0,1.0,1.0]},
  {"NAME":"ColorB","LABEL":"Colour 2","TYPE":"color","DEFAULT":[0.35,0.75,1.0,1.0]},
  {"NAME":"Opacity","LABEL":"Opacity","TYPE":"float","DEFAULT":0.9,"MIN":0.05,"MAX":1.0}
 ],"ISFVSN":"2"
}*/
float hs(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
void main(){
 vec2 p=gl_FragCoord.xy;float cell=max(2.0,Size*3.0);vec2 g=floor(p/cell);float seed=hs(g);float fall=TIME*Speed*(4.0+seed*7.0);vec2 q=mod(p+vec2(-Wind*fall,fall),cell)-cell*.5;float live=step(1.0-Density*.55,seed);float r=length(q);float mark=0.0;
 if(Style==0)mark=1.0-smoothstep(Size,Size+1.0,r);
 else if(Style==1){mark=step(abs(q.x),Size)*step(abs(q.y),max(1.0,Size*.6));}
 else if(Style==2){mark=(1.0-smoothstep(Size,Size+.7,abs(r-Size*.72)))*step(.2,r);}
 else if(Style==3){mark=max(step(abs(q.x),.65)*step(abs(q.y),Size),step(abs(q.y),.65)*step(abs(q.x),Size));}
 else {float heart=min(length(q-vec2(-Size*.45,Size*.25)),length(q-vec2(Size*.45,Size*.25)));float tip=length(vec2(q.x*.75,q.y+Size*.45));mark=max(1.0-smoothstep(Size*.6,Size*.9,heart),1.0-smoothstep(Size*.55,Size*.9,tip));}
 vec3 col=mix(ColorA.rgb,ColorB.rgb,hs(g+17.0));gl_FragColor=vec4(col,clamp(mark*live*Opacity,0.0,1.0));
}
