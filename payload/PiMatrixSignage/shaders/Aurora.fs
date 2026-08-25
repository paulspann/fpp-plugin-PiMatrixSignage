/*{
  "TITLE":"Aurora Ribbons","DESCRIPTION":"Soft low-resolution aurora ribbons with calm, curtain and vivid styles.","CREDIT":"Pi Matrix Signage","CATEGORIES":["Built-in","Aurora","Generator"],
  "INPUTS":[
    {"NAME":"Style","LABEL":"Style","TYPE":"long","DEFAULT":0,"VALUES":[0,1,2],"LABELS":["Calm ribbons","Curtains","Vivid waves"]},
    {"NAME":"Speed","LABEL":"Speed","TYPE":"float","DEFAULT":0.6,"MIN":0.05,"MAX":3.0},
    {"NAME":"Bands","LABEL":"Bands","TYPE":"float","DEFAULT":3.5,"MIN":1.0,"MAX":8.0},
    {"NAME":"Width","LABEL":"Ribbon width","TYPE":"float","DEFAULT":0.12,"MIN":0.03,"MAX":0.35},
    {"NAME":"Shimmer","LABEL":"Shimmer","TYPE":"float","DEFAULT":0.3,"MIN":0.0,"MAX":1.0},
    {"NAME":"ColorA","LABEL":"Colour 1","TYPE":"color","DEFAULT":[0.15,0.85,0.45,1.0]},
    {"NAME":"ColorB","LABEL":"Colour 2","TYPE":"color","DEFAULT":[0.18,0.35,1.0,1.0]},
    {"NAME":"ColorC","LABEL":"Highlight","TYPE":"color","DEFAULT":[0.65,0.25,1.0,1.0]},
    {"NAME":"Opacity","LABEL":"Opacity","TYPE":"float","DEFAULT":0.92,"MIN":0.05,"MAX":1.0}
  ],"ISFVSN":"2"
}*/
void main(){
 vec2 uv=gl_FragCoord.xy/max(RENDERSIZE,vec2(1.0));float t=TIME*Speed;float w=max(.01,Width);
 float base=.52+.17*sin(uv.x*Bands*6.283+t)+.06*sin(uv.x*13.0-t*1.7);
 float a=exp(-abs(uv.y-base)/w);float b=exp(-abs(uv.y-(base-.18-.04*sin(t+uv.x*8.0)))/(w*.72))*.65;
 float c=0.0;if(Style>=1)c=exp(-abs(uv.y-(base+.16+.05*sin(t*.7-uv.x*10.0)))/(w*.55))*.45;
 float curtain=1.0;if(Style==1)curtain=.55+.45*(.5+.5*sin(uv.x*RENDERSIZE.x*.45+t*2.0));
 float vivid=Style==2?(.78+.35*sin(uv.y*22.0+uv.x*7.0-t*2.4)):1.0;
 float glow=(a+b+c)*curtain*vivid;float shimmer=1.0+Shimmer*.28*sin(t*5.0+uv.x*17.0+uv.y*9.0);
 vec3 col=mix(ColorB.rgb,ColorA.rgb,clamp(uv.x+.18*sin(t),0.0,1.0));col=mix(col,ColorC.rgb,clamp(c+.22*a*sin(t+uv.x*5.0),0.0,.65));
 gl_FragColor=vec4(col*glow*shimmer,clamp(glow*Opacity,0.0,1.0));
}
