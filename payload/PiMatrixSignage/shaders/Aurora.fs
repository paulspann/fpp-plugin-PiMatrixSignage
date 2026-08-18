/*{
  "DESCRIPTION":"LED Aurora",
  "CREDIT":"Pi Matrix Signage",
  "CATEGORIES":["Built-in","Generator"],
  "INPUTS":[
    {"NAME":"Speed","TYPE":"float","DEFAULT":0.6,"MIN":0.05,"MAX":3.0},
    {"NAME":"Bands","TYPE":"float","DEFAULT":3.5,"MIN":1.0,"MAX":8.0},
    {"NAME":"ColorA","TYPE":"color","DEFAULT":[0.15,0.85,0.45,1.0]},
    {"NAME":"ColorB","TYPE":"color","DEFAULT":[0.18,0.35,1.0,1.0]}
  ],"ISFVSN":"2"
}*/
void main(){
  vec2 uv=gl_FragCoord.xy/RENDERSIZE.xy;
  float t=TIME*Speed;
  float wave=.5+.18*sin(uv.x*Bands*6.283+t)+.08*sin(uv.x*11.0-t*1.7);
  float glow=max(0.0,1.0-abs(uv.y-wave)*7.0);
  float glow2=max(0.0,1.0-abs(uv.y-(wave-.18))*10.0)*.55;
  vec3 col=mix(ColorB.rgb,ColorA.rgb,uv.x+.2*sin(t));
  gl_FragColor=vec4(col*(glow+glow2),1.0);
}
