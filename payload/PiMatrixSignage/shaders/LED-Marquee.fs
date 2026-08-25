/*{
 "TITLE":"LED Marquee Chase","DESCRIPTION":"Chasing LED border for sale, open, event and attention signs.","CREDIT":"Pi Matrix Signage","CATEGORIES":["Built-in","Marquee","Generator"],
 "INPUTS":[
  {"NAME":"Speed","LABEL":"Chase speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":5.0},
  {"NAME":"Spacing","LABEL":"Lamp spacing","TYPE":"float","DEFAULT":4.0,"MIN":2.0,"MAX":12.0},
  {"NAME":"Thickness","LABEL":"Border thickness","TYPE":"float","DEFAULT":1.5,"MIN":1.0,"MAX":5.0},
  {"NAME":"ColorA","LABEL":"Colour 1","TYPE":"color","DEFAULT":[1.0,0.15,0.05,1.0]},
  {"NAME":"ColorB","LABEL":"Colour 2","TYPE":"color","DEFAULT":[1.0,0.85,0.1,1.0]},
  {"NAME":"BackgroundOpacity","LABEL":"Inside opacity","TYPE":"float","DEFAULT":0.0,"MIN":0.0,"MAX":1.0},
  {"NAME":"Background","LABEL":"Inside colour","TYPE":"color","DEFAULT":[0.0,0.0,0.0,1.0]}
 ],"ISFVSN":"2"
}*/
void main(){vec2 p=gl_FragCoord.xy;float w=RENDERSIZE.x,h=RENDERSIZE.y;float edge=min(min(p.x,w-1.0-p.x),min(p.y,h-1.0-p.y));float border=1.0-smoothstep(Thickness,Thickness+1.0,edge);float per=2.0*(w+h);float s;if(p.y<Thickness+1.0)s=p.x;else if(p.x>w-Thickness-2.0)s=w+p.y;else if(p.y>h-Thickness-2.0)s=w+h+(w-p.x);else s=2.0*w+h+(h-p.y);float phase=mod(floor(s/max(Spacing,1.0))+floor(TIME*Speed*8.0),2.0);vec3 lamp=mix(ColorA.rgb,ColorB.rgb,phase);vec3 col=mix(Background.rgb,lamp,border);float a=max(border,BackgroundOpacity*(1.0-border));gl_FragColor=vec4(col,a);}
