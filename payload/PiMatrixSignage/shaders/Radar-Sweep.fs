/*{
 "TITLE":"Radar Sweep","DESCRIPTION":"Rotating radar beam with grid rings and fading blips.","CREDIT":"Pi Matrix Signage","CATEGORIES":["Built-in","Radar","Generator"],
 "INPUTS":[
  {"NAME":"Speed","LABEL":"Sweep speed","TYPE":"float","DEFAULT":0.75,"MIN":0.05,"MAX":3.0},
  {"NAME":"Trail","LABEL":"Beam trail","TYPE":"float","DEFAULT":0.3,"MIN":0.05,"MAX":0.9},
  {"NAME":"Grid","LABEL":"Grid brightness","TYPE":"float","DEFAULT":0.22,"MIN":0.0,"MAX":1.0},
  {"NAME":"Blips","LABEL":"Blips","TYPE":"float","DEFAULT":0.65,"MIN":0.0,"MAX":1.0},
  {"NAME":"SweepColor","LABEL":"Sweep colour","TYPE":"color","DEFAULT":[0.1,1.0,0.3,1.0]},
  {"NAME":"Background","LABEL":"Background","TYPE":"color","DEFAULT":[0.0,0.055,0.015,1.0]}
 ],"ISFVSN":"2"
}*/
float h(float n){return fract(sin(n*77.73)*43758.5453);}
void main(){vec2 uv=(gl_FragCoord.xy-RENDERSIZE*.5)/max(min(RENDERSIZE.x,RENDERSIZE.y)*.5,1.0);float r=length(uv),a=atan(uv.y,uv.x);float sweep=mod(TIME*Speed*2.0,6.28318)-3.14159;float da=mod(a-sweep+9.42477,6.28318)-3.14159;float beam=exp(-max(0.0,da)*max(2.0,9.0*(1.0-Trail)))*step(0.0,da);float rings=(1.0-smoothstep(.035,.065,abs(fract(r*4.0)-.5)))*Grid;float axes=(1.0-smoothstep(.015,.035,min(abs(uv.x),abs(uv.y))))*Grid*.75;float bl=0.0;for(int i=0;i<5;i++){float fi=float(i);vec2 bp=vec2(h(fi*4.1+2.0)*1.45-.725,h(fi*7.7+9.0)*1.45-.725);float hit=1.0-smoothstep(.035,.075,distance(uv,bp));float ba=atan(bp.y,bp.x);float age=mod(sweep-ba+6.28318,6.28318);bl=max(bl,hit*exp(-age*1.5)*Blips);}float mask=step(r,1.0);vec3 col=Background.rgb+SweepColor.rgb*(beam*.8+rings+axes+bl);gl_FragColor=vec4(col,mask);}
