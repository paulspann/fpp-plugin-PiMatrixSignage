/*{
  "TITLE":"Sky Weather",
  "DESCRIPTION":"Animated sky with sun or moon, layered moving clouds, rain, snow and storm modes for low-resolution LED displays.",
  "CREDIT":"Pi Matrix Signage",
  "CATEGORIES":["Built-in","Sky","Weather","Generator"],
  "INPUTS":[
    {"NAME":"Weather","LABEL":"Weather","TYPE":"long","DEFAULT":1,"VALUES":[0,1,2,3,4,5],"LABELS":["Clear","Partly cloudy","Overcast","Rain","Snow","Storm"]},
    {"NAME":"SkyPhase","LABEL":"Sky phase","TYPE":"long","DEFAULT":0,"VALUES":[0,1,2],"LABELS":["Day","Sunset","Night"]},
    {"NAME":"Speed","LABEL":"Cloud / weather speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":4.0},
    {"NAME":"WindDirection","LABEL":"Wind direction","TYPE":"long","DEFAULT":0,"VALUES":[0,1],"LABELS":["Left to right","Right to left"]},
    {"NAME":"CloudCover","LABEL":"Total cloud cover","TYPE":"float","DEFAULT":0.55,"MIN":0.0,"MAX":1.0},
    {"NAME":"LowCloudCover","LABEL":"Low cloud cover","TYPE":"float","DEFAULT":0.55,"MIN":0.0,"MAX":1.0},
    {"NAME":"MidCloudCover","LABEL":"Mid cloud cover","TYPE":"float","DEFAULT":0.55,"MIN":0.0,"MAX":1.0},
    {"NAME":"HighCloudCover","LABEL":"High cloud cover","TYPE":"float","DEFAULT":0.55,"MIN":0.0,"MAX":1.0},
    {"NAME":"PrecipIntensity","LABEL":"Rain / snow intensity","TYPE":"float","DEFAULT":0.65,"MIN":0.0,"MAX":1.0},
    {"NAME":"SunSize","LABEL":"Sun / moon size","TYPE":"float","DEFAULT":0.12,"MIN":0.04,"MAX":0.28},
    {"NAME":"MoonPhase","LABEL":"Moon cycle (manual)","TYPE":"float","DEFAULT":0.5,"MIN":0.0,"MAX":1.0},
    {"NAME":"MoonBrightness","LABEL":"Moon brightness","TYPE":"float","DEFAULT":0.95,"MIN":0.1,"MAX":1.0},
    {"NAME":"SunMoonPosition","LABEL":"Sun / moon position","TYPE":"float","DEFAULT":0.72,"MIN":0.0,"MAX":1.0},
    {"NAME":"SunMoonHeight","LABEL":"Sun / moon height","TYPE":"float","DEFAULT":0.72,"MIN":0.05,"MAX":0.95},
    {"NAME":"SunMoonMovement","LABEL":"Sun / moon movement","TYPE":"long","DEFAULT":0,"VALUES":[0,1,2],"LABELS":["Stationary","Left to right","Right to left"]},
    {"NAME":"SunMoonSpeed","LABEL":"Sun / moon speed","TYPE":"float","DEFAULT":0.15,"MIN":0.01,"MAX":1.0},
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

  float bodyX=clamp(SunMoonPosition,0.0,1.0);
  if(SunMoonMovement!=0){
    float celestialDir=(SunMoonMovement==1)?1.0:-1.0;
    bodyX=mod(bodyX+celestialDir*TIME*max(SunMoonSpeed,0.001)*0.018+1.14,1.28)-0.14;
  }
  float bodyY=1.0-clamp(SunMoonHeight,0.05,0.95);
  vec2 bodyPos=vec2(bodyX,bodyY);
  float bodyRadius=clamp(SunSize,0.02,0.35);
  // Keep the celestial body circular in physical LED pixels even on very wide
  // signage canvases. SunSize remains relative to display height.
  vec2 bodyDelta=vec2((p.x-bodyPos.x)*(W/H),p.y-bodyPos.y);
  float bodyDist=length(bodyDelta);
  float body=1.0-smoothstep(bodyRadius,bodyRadius+max(0.004,bodyRadius*0.12),bodyDist);
  float glowRadius=bodyRadius*1.75;
  float glow=1.0-smoothstep(glowRadius,glowRadius+max(0.004,glowRadius*0.12),bodyDist);
  if(SkyPhase==2){
    // Project a lit hemisphere onto the visible moon disc. MoonPhase is a
    // synodic cycle: 0=new, .25=first quarter, .5=full, .75=last quarter.
    // This produces crescents/quarters/gibbous phases without texture detail
    // that would disappear on a low-resolution P5/P10 matrix.
    vec2 moonXY=bodyDelta/max(bodyRadius,0.001);
    float moonR2=dot(moonXY,moonXY);
    float moonZ=sqrt(max(0.0,1.0-moonR2));
    float phaseAngle=fract(MoonPhase)*6.28318530718;
    vec3 moonNormal=vec3(moonXY.x,moonXY.y,moonZ);
    vec3 moonLight=vec3(sin(phaseAngle),0.0,-cos(phaseAngle));
    float terminator=dot(moonNormal,moonLight);
    float litHemisphere=smoothstep(-0.055,0.055,terminator);
    float illumination=0.5*(1.0-cos(phaseAngle));
    float moonLit=body*litHemisphere*step(moonR2,1.0);
    vec3 moonColor=vec3(0.76,0.86,1.0)*clamp(MoonBrightness,0.1,1.0);
    col=mix(col,moonColor,glow*0.16*sqrt(max(illumination,0.0)));
    col=mix(col,moonColor,moonLit*0.98*step(0.004,illumination));
  }else{
    vec3 bodyColor=(SkyPhase==1)?vec3(1.0,0.34,0.06):vec3(1.0,0.86,0.22);
    col=mix(col,bodyColor,glow*0.20);
    col=mix(col,bodyColor,body*0.96);
  }

  float requested=clamp(CloudCover,0.0,1.0);
  float weatherCover=(Weather==0)?0.0:((Weather==1)?0.38:((Weather==2)?0.82:0.92));
  float cover=clamp(max(requested,weatherCover),0.0,1.0);
  float lowCover=clamp(max(LowCloudCover,(Weather>=2)?cover*0.72:0.0),0.0,1.0);
  float midCover=clamp(max(MidCloudCover,(Weather>=2)?cover*0.58:0.0),0.0,1.0);
  float highCover=clamp(max(HighCloudCover,(Weather>=2)?cover*0.42:0.0),0.0,1.0);

  // High total cloud should look like an actual sky deck, not merely every
  // member of a sparse set of isolated cloud puffs.  This broad, softly
  // textured veil removes the large blue holes that were still visible at
  // 100% live cloud cover while retaining motion/detail on a 32/64px matrix.
  float overcast=smoothstep(0.68,0.96,cover);
  float deckCellX=floor((p.x+dir*t*0.010)*W/8.0);
  float deckCellY=floor(p.y*H/6.0);
  float deckNoise=0.78+0.22*hash1(deckCellX+deckCellY*37.0);
  float deckDepth=max(cover,clamp((lowCover+midCover)*0.5,0.0,1.0));
  float deckHeight=mix(0.68,1.0,deckDepth);
  float deckMask=(1.0-smoothstep(deckHeight,1.08,p.y))*overcast*deckNoise;
  float overcastShade=mix(0.76,0.50,clamp(lowCover*0.7+midCover*0.3,0.0,1.0));
  if(Weather==5)overcastShade*=0.72;
  vec3 deckRgb=CloudColor.rgb*overcastShade;
  col=mix(col,deckRgb,clamp(deckMask*(0.82+0.16*cover),0.0,0.98));

  float cloud=0.0;
  for(int layer=0;layer<3;layer++){
    float fl=float(layer);
    float layerCover=(layer==0)?highCover:((layer==1)?midCover:lowCover);
    float y=0.17+fl*0.20;
    float scale=0.080+fl*0.034;
    float layerSpeed=(0.015+fl*0.010)*t*dir;
    // Increase both density and puff width with layer coverage.  At 100% this
    // becomes an overlapping deck; lower values still read as separate clouds.
    float densityScale=mix(0.88,1.58,layerCover);
    for(int i=0;i<9;i++){
      float fi=float(i);
      float seed=fi+fl*19.0;
      float spacing=1.0/9.0;
      float x=mod(fi*spacing+hash1(seed)*0.10+layerSpeed+2.0,1.22)-0.11;
      float shown=step(hash1(seed*2.7),layerCover);
      vec2 c=vec2(x,y+(hash1(seed*5.1)-0.5)*0.085);
      float a=cloudBlob(p,c,vec2(scale*densityScale*(1.55+hash1(seed)*0.65),scale*0.62*densityScale));
      float b=cloudBlob(p,c+vec2(scale*0.58,-scale*0.20),vec2(scale*densityScale,scale*0.82*densityScale));
      float d=cloudBlob(p,c-vec2(scale*0.55,scale*0.10),vec2(scale*0.85*densityScale,scale*0.68*densityScale));
      cloud=max(cloud,max(a,max(b,d))*shown);
    }
  }
  // Dense overcast clouds lose the bright-white fair-weather look.  Keep
  // broken cloud bright, then progressively grey the visible deck as total
  // coverage approaches 100%.
  float cloudShade=mix(1.0,0.62,cover);
  if(Weather==3||Weather==4)cloudShade=min(cloudShade,0.58);
  if(Weather==5)cloudShade=0.32;
  vec3 cloudRgb=CloudColor.rgb*cloudShade;
  col=mix(col,cloudRgb,cloud*(0.56+cover*0.40));

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
