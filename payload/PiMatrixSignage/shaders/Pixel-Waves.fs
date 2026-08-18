/*{
  "DESCRIPTION":"Pixel Waves",
  "CREDIT":"Pi Matrix Signage",
  "CATEGORIES":["Built-in","Generator"],
  "INPUTS":[
    {"NAME":"Speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":5.0},
    {"NAME":"Width","TYPE":"float","DEFAULT":6.0,"MIN":2.0,"MAX":20.0},
    {"NAME":"ColorA","TYPE":"color","DEFAULT":[0.71,0.85,0.54,1.0]},
    {"NAME":"ColorB","TYPE":"color","DEFAULT":[0.89,0.70,0.76,1.0]}
  ],"ISFVSN":"2"
}*/
void main(){
  float t=TIME*Speed;
  vec2 p=gl_FragCoord.xy;
  float a=sin((p.x+p.y*.7)/Width+t);
  float b=sin((p.x*.6-p.y)/Width-t*.8);
  float v=.5+.5*sin((a+b)*2.2);
  gl_FragColor=vec4(mix(ColorA.rgb,ColorB.rgb,v),1.0);
}
