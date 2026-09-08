/*{
 "TITLE":"Neon Chevrons – Right",
 "DESCRIPTION":"Seamlessly looping neon chevrons travelling to the right on a dark background. Generated live; no video file required.",
 "CREDIT":"Pi Matrix Signage",
 "CATEGORIES":["Built-in","Directional","Neon","Generator"],
 "INPUTS":[
  {"NAME":"Speed","LABEL":"Travel speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":5.0},
  {"NAME":"ChevronWidth","LABEL":"Chevron width (LED px)","TYPE":"float","DEFAULT":18.0,"MIN":4.0,"MAX":64.0},
  {"NAME":"Spacing","LABEL":"Gap (LED px)","TYPE":"float","DEFAULT":8.0,"MIN":0.0,"MAX":40.0},
  {"NAME":"Height","LABEL":"Height %","TYPE":"float","DEFAULT":82.0,"MIN":20.0,"MAX":100.0},
  {"NAME":"Thickness","LABEL":"Tube thickness (LED px)","TYPE":"float","DEFAULT":1.5,"MIN":0.5,"MAX":8.0},
  {"NAME":"Glow","LABEL":"Neon glow","TYPE":"float","DEFAULT":4.0,"MIN":0.5,"MAX":16.0},
  {"NAME":"Pulse","LABEL":"Brightness pulse","TYPE":"float","DEFAULT":0.45,"MIN":0.0,"MAX":1.0},
  {"NAME":"ArrowColor","LABEL":"Chevron colour","TYPE":"color","DEFAULT":[1.0,1.0,1.0,1.0]},
  {"NAME":"Background","LABEL":"Background colour","TYPE":"color","DEFAULT":[0.0,0.0,0.0,1.0]},
  {"NAME":"BackgroundOpacity","LABEL":"Background opacity","TYPE":"float","DEFAULT":1.0,"MIN":0.0,"MAX":1.0}
 ],"ISFVSN":"2"
}*/
void main(){
  vec2 p=gl_FragCoord.xy;
  float chevron=max(4.0,ChevronWidth);
  float period=chevron+max(0.0,Spacing);
  float travel=TIME*Speed*period;
  float shifted=p.x-travel;
  float cell=floor((shifted+period*.5)/period);
  float x=mod(shifted+period*.5,period)-period*.5;
  float halfHeight=max(1.0,RENDERSIZE.y*clamp(Height,20.0,100.0)*.005);
  float y=p.y-RENDERSIZE.y*.5;
  float target=chevron*.5-abs(y)*(chevron/halfHeight);
  float distanceToTube=abs(x-target)/sqrt(1.0+(chevron/halfHeight)*(chevron/halfHeight));
  float within=1.0-smoothstep(halfHeight,halfHeight+1.0,abs(y));
  float core=(1.0-smoothstep(max(.1,Thickness*.35),Thickness,distanceToTube))*within;
  float halo=exp(-distanceToTube*distanceToTube/max(.25,Glow*Glow))*within;
  float wave=.5+.5*sin(cell*1.35-TIME*Speed*4.0);
  float brightness=mix(1.0,mix(.35,1.0,wave),clamp(Pulse,0.0,1.0));
  float light=clamp((core+halo*.72)*brightness,0.0,1.0);
  vec3 colour=mix(Background.rgb,ArrowColor.rgb,light);
  float alpha=max(BackgroundOpacity,light*ArrowColor.a);
  gl_FragColor=vec4(colour,alpha);
}
