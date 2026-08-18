/*{
  "DESCRIPTION":"LED Plasma",
  "CREDIT":"Pi Matrix Signage",
  "CATEGORIES":["Built-in","Generator"],
  "INPUTS":[
    {"NAME":"Speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":4.0},
    {"NAME":"Scale","TYPE":"float","DEFAULT":5.0,"MIN":1.0,"MAX":12.0},
    {"NAME":"ColorA","TYPE":"color","DEFAULT":[0.72,0.29,0.13,1.0]},
    {"NAME":"ColorB","TYPE":"color","DEFAULT":[0.0,0.22,0.28,1.0]}
  ],"ISFVSN":"2"
}*/
void main(){
  vec2 uv=(gl_FragCoord.xy/RENDERSIZE.xy)*Scale;
  float t=TIME*Speed;
  float v=sin(uv.x+t)+sin(uv.y*1.3-t*.7)+sin((uv.x+uv.y)*.7+t*.45);
  v=.5+.5*sin(v*1.4);
  gl_FragColor=vec4(mix(ColorA.rgb,ColorB.rgb,v),1.0);
}
