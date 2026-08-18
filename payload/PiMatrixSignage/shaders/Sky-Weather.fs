/*{
  "TITLE":"Sky Weather",
  "DESCRIPTION":"Animated sky with sun or moon, layered moving clouds, rain, snow and storm modes for low-resolution LED displays.",
  "CREDIT":"Pi Matrix Signage",
  "CATEGORIES":["Built-in","Sky","Weather","Generator"],
  "INPUTS":[
    {"NAME":"Weather","LABEL":"Weather","TYPE":"long","DEFAULT":1,"VALUES":[0,1,2,3,4,5],"LABELS":["Clear","Partly cloudy","Overcast","Rain","Snow","Storm"]},
    {"NAME":"SkyPhase","LABEL":"Sky phase","TYPE":"long","DEFAULT":0,"VALUES":[0,1,2],"LABELS":["Day","Sunset","Night"]},
    {"NAME":"Speed","LABEL":"Movement speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":4.0},
    {"NAME":"WindDirection","LABEL":"Wind direction","TYPE":"long","DEFAULT":0,"VALUES":[0,1],"LABELS":["Left to right","Right to left"]},
    {"NAME":"CloudCover","LABEL":"Cloud cover","TYPE":"float","DEFAULT":0.55,"MIN":0.0,"MAX":1.0},
    {"NAME":"PrecipIntensity","LABEL":"Rain / snow intensity","TYPE":"float","DEFAULT":0.65,"MIN":0.0,"MAX":1.0},
    {"NAME":"SunSize","LABEL":"Sun / moon size","TYPE":"float","DEFAULT":0.12,"MIN":0.04,"MAX":0.28},
    {"NAME":"HorizonGlow","LABEL":"Horizon glow","TYPE":"float","DEFAULT":0.35,"MIN":0.0,"MAX":1.0},
    {"NAME":"SkyTop","LABEL":"Sky top","TYPE":"color","DEFAULT":[0.08,0.35,0.72,1.0]},
    {"NAME":"SkyBottom","LABEL":"Sky horizon","TYPE":"color","DEFAULT":[0.45,0.78,1.0,1.0]},
    {"NAME":"CloudColor","LABEL":"Cloud colour","TYPE":"color","DEFAULT":[0.92,0.95,1.0,1.0]},
    {"NAME":"RainColor","LABEL":"Rain colour","TYPE":"color","DEFAULT":[0.42,0.72,1.0,1.0]},
    {"NAME":"SnowColor","LABEL":"Snow colour","TYPE":"color","DEFAULT":[1.0,1.0,1.0,1.0]}
  ],
  "ISFVSN":"2"
}*/

float hash1(float n){return fract(sin(n*127.1)*43758.5453);}

float softCircle(vec2 p,vec2 c,float r){
  return 1.0-smoothstep(r,r+max(0.004,r*0.12),distance(p,c));
}

float cloudBlob(vec2 p,vec2 c,vec2 size){
  vec2 q=(p-c)/max(size,vec2(0.001));
  return 1.0-smoothstep(0.78,1.05,dot(q,q));
}

void main(){
  float W=max(RENDERSIZE.x,1.0);
  float H=max(RENDERSIZE.y,1.0);
  vec2 p=vec2(gl_FragCoord.x/W,(H-gl_FragCoord.y)/H);
  float t=TIME*max(Speed,0.01);
  float dir=(WindDirection==0)?1.0:-1.0;

  vec3 top=SkyTop.rgb;
  vec3 bottom=SkyBottom.rgb;
  if(SkyPhase==1){
    top=mix(top,vec3(0.16,0.06,0.34),0.55);
    bottom=mix(bottom,vec3(1.0,0.30,0.08),0.72);
  }else if(SkyPhase==2){
    top=mix(top,vec3(0.005,0.012,0.055),0.92);
    bottom=mix(bottom,vec3(0.04,0.10,0.22),0.82);
  }
  float horizon=pow(clamp(1.0-p.y,0.0,1.0),3.0)*clamp(HorizonGlow,0.0,1.0);
  vec3 col=mix(bottom,top,smoothstep(0.0,0.92,p.y));
  col+=vec3(1.0,0.48,0.16)*horizon*(SkyPhase==2?0.10:0.24);

  if(SkyPhase==2){
    float stars=step(0.976,hash1(floor(p.x*W)+floor(p.y*H)*131.0));
    col=mix(col,vec3(0.78,0.88,1.0),stars*(1.0-p.y)*0.8);
  }

  float orbit=mod(t*0.018,1.28)-0.14;
  float bodyX=(dir>0.0)?orbit:(1.0-orbit);
  vec2 bodyPos=vec2(bodyX,SkyPhase==1?0.48:0.27);
  float body=softCircle(p,bodyPos,clamp(SunSize,0.02,0.35));
  float glow=softCircle(p,bodyPos,clamp(SunSize,0.02,0.35)*1.75);
  vec3 bodyColor=(SkyPhase==2)?vec3(0.76,0.86,1.0):((SkyPhase==1)?vec3(1.0,0.34,0.06):vec3(1.0,0.86,0.22));
  col=mix(col,bodyColor,glow*0.20);
  col=mix(col,bodyColor,body*0.96);

  float requested=clamp(CloudCover,0.0,1.0);
  float weatherCover=(Weather==0)?0.0:((Weather==1)?0.38:((Weather==2)?0.82:0.92));
  float cover=clamp(max(requested,weatherCover),0.0,1.0);
  float cloud=0.0;
  for(int layer=0;layer<3;layer++){
    float fl=float(layer);
    float y=0.20+fl*0.19;
    float scale=0.075+fl*0.022;
    float layerSpeed=(0.020+fl*0.009)*t*dir;
    for(int i=0;i<7;i++){
      float fi=float(i);
      float seed=fi+fl*17.0;
      float spacing=1.0/7.0;
      float x=mod(fi*spacing+hash1(seed)*0.12+layerSpeed+2.0,1.20)-0.10;
      float shown=step(hash1(seed*2.7),cover);
      vec2 c=vec2(x,y+(hash1(seed*5.1)-0.5)*0.075);
      float a=cloudBlob(p,c,vec2(scale*(1.55+hash1(seed)*0.65),scale*0.62));
      float b=cloudBlob(p,c+vec2(scale*0.58,-scale*0.20),vec2(scale,scale*0.82));
      float d=cloudBlob(p,c-vec2(scale*0.55,scale*0.10),vec2(scale*0.85,scale*0.68));
      cloud=max(cloud,max(a,max(b,d))*shown);
    }
  }
  float cloudShade=mix(1.0,0.52,step(2.5,float(Weather)));
  if(Weather==5)cloudShade=0.32;
  vec3 cloudRgb=CloudColor.rgb*cloudShade;
  col=mix(col,cloudRgb,cloud*(0.62+cover*0.32));

  float intensity=clamp(PrecipIntensity,0.0,1.0);
  if(Weather==3||Weather==5){
    float rain=0.0;
    for(int i=0;i<28;i++){
      float fi=float(i);
      float active=step(hash1(fi*8.3),intensity);
      float x=fract(hash1(fi*2.1)+fi/28.0+dir*t*0.045);
      float y=fract(hash1(fi*4.7)+t*(0.65+hash1(fi)*0.45));
      float dx=abs(p.x-x+dir*(p.y-y)*0.035);
      float dy=abs(p.y-y);
      float streak=(1.0-smoothstep(0.004,0.014,dx))*(1.0-smoothstep(0.025,0.085,dy));
      rain=max(rain,streak*active);
    }
    col=mix(col,RainColor.rgb,rain*0.88);
  }else if(Weather==4){
    float snow=0.0;
    for(int i=0;i<24;i++){
      float fi=float(i);
      float active=step(hash1(fi*7.9),intensity);
      float fall=fract(hash1(fi*3.3)+t*(0.10+hash1(fi)*0.10));
      float sway=sin(t*(0.7+hash1(fi))+fi)*0.035;
      float x=fract(hash1(fi*5.7)+fi/24.0+dir*t*0.012+sway);
      float r=mix(0.005,0.016,hash1(fi*11.0));
      snow=max(snow,softCircle(p,vec2(x,fall),r)*active);
    }
    col=mix(col,SnowColor.rgb,snow);
  }

  if(Weather==5){
    float flash=step(0.975,hash1(floor(t*1.7)))*exp(-fract(t*1.7)*12.0);
    float boltX=0.25+hash1(floor(t*1.7)*3.0)*0.50;
    float bolt=1.0-smoothstep(0.006,0.026,abs(p.x-boltX-sin(p.y*31.0)*0.018));
    bolt*=step(0.28,p.y)*step(p.y,0.92)*flash;
    col+=vec3(0.72,0.82,1.0)*(flash*0.48+bolt);
  }

  gl_FragColor=vec4(clamp(col,0.0,1.0),1.0);
}
