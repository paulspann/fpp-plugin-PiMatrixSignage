/*{
  "TITLE":"Cars on Road",
  "DESCRIPTION":"Pixel-sized side-view cars for very short LED strips",
  "CREDIT":"Pi Matrix Signage",
  "CATEGORIES":["Built-in","Generator"],
  "INPUTS":[
    {"NAME":"Speed","TYPE":"float","DEFAULT":1.0,"MIN":0.1,"MAX":4.0},
    {"NAME":"Direction","TYPE":"int","DEFAULT":0,"VALUES":[0,1],"LABELS":["Left to right","Right to left"]},
    {"NAME":"TrafficDensity","TYPE":"int","DEFAULT":4,"MIN":2,"MAX":7,"LABEL":"Cars"},
    {"NAME":"CarScale","TYPE":"float","DEFAULT":1.0,"MIN":0.65,"MAX":1.35,"LABEL":"Car size"},
    {"NAME":"RoadColor","TYPE":"color","DEFAULT":[0.16,0.16,0.18,1.0]},
    {"NAME":"HeadlightColor","TYPE":"color","DEFAULT":[1.0,1.0,0.80,1.0]},
    {"NAME":"TaillightColor","TYPE":"color","DEFAULT":[1.0,0.12,0.05,1.0]}
  ],"ISFVSN":"2"
}*/

float boxMask(vec2 p, vec2 c, vec2 halfSize){
  vec2 d = abs(p-c)-halfSize;
  return 1.0-step(0.0,max(d.x,d.y));
}

float circleMask(vec2 p, vec2 c, float r){
  return 1.0-step(r,length(p-c));
}

vec3 carColour(float seed){
  float s=fract(seed*13.71);
  if(s<0.20) return vec3(0.10,0.55,1.00);
  if(s<0.40) return vec3(1.00,0.20,0.12);
  if(s<0.60) return vec3(1.00,0.78,0.08);
  if(s<0.80) return vec3(0.25,0.90,0.40);
  return vec3(0.82,0.32,1.00);
}

void main(){
  float W=max(RENDERSIZE.x,1.0);
  float H=max(RENDERSIZE.y,1.0);
  // Work in normal top-to-bottom display coordinates, not OpenGL bottom-up coordinates.
  vec2 p=vec2(gl_FragCoord.x,H-gl_FragCoord.y);
  float dir=(Direction==0)?1.0:-1.0;

  // Deliberately pixel-sized rather than proportional road geometry.
  // At H=16 this gives cars about 8-9 pixels high and ~17-20 pixels long.
  float carH=clamp(H*0.72*CarScale,7.0,min(14.0,H*0.88));
  float carW=carH*2.15;
  float wheelR=max(1.0,carH*0.14);
  float baseY=clamp(H*0.63,carH*0.45,H-3.0);

  vec3 rgb=vec3(0.0);
  float alpha=0.0;

  // Only a tiny road/base strip: at 16px high this is 2 pixels or so.
  float roadTop=max(0.0,baseY+carH*0.35);
  float road=step(roadTop,p.y)*(1.0-step(min(H,roadTop+max(2.0,H*0.12)),p.y));
  rgb=mix(rgb,RoadColor.rgb,road);
  alpha=max(alpha,road*0.95);

  int count=TrafficDensity;
  if(count<2) count=2;
  if(count>7) count=7;

  for(int i=0;i<7;i++){
    if(i>=count) break;
    float fi=float(i);
    float seed=fi*0.173+0.117;
    float spacing=W/float(count);
    float travel=W+carW*2.0;
    float start=fi*spacing+seed*spacing*0.55;
    float motion=TIME*Speed*(18.0+H*0.85);
    // Advance one common track left-to-right, then mirror that track for
    // right-to-left.  Do not reverse motion *and* mirror the coordinate,
    // because that double reversal makes a left-facing car still travel right.
    float track=mod(start+motion+travel*4.0,travel)-carW;
    float cx=(dir>0.0)?track:(W-track);

    // Stagger vertically by one pixel so a long strip does not look mechanically flat.
    float cy=baseY+(mod(fi,3.0)-1.0)*min(1.0,H*0.05);
    vec2 c=vec2(cx,cy);

    // Body is intentionally chunky so it survives a 16px render.
    float body=boxMask(p,c+vec2(0.0,carH*0.04),vec2(carW*0.50,carH*0.22));
    float lower=boxMask(p,c+vec2(-dir*carW*0.02,carH*0.20),vec2(carW*0.42,carH*0.12));
    float roof=boxMask(p,c+vec2(-dir*carW*0.06,-carH*0.20),vec2(carW*0.23,carH*0.17));
    float bonnet=boxMask(p,c+vec2(dir*carW*0.39,-carH*0.03),vec2(carW*0.12,carH*0.14));
    float car=max(max(body,lower),max(roof,bonnet));

    vec3 cc=carColour(seed);
    rgb=mix(rgb,cc,car);
    alpha=max(alpha,car);

    // Bright 1-2 pixel window patch gives a recognisable side-view roofline.
    float window=boxMask(p,c+vec2(-dir*carW*0.05,-carH*0.20),vec2(carW*0.12,max(1.0,carH*0.07)));
    rgb=mix(rgb,vec3(0.55,0.82,1.0),window*0.90);
    alpha=max(alpha,window);

    // Wheels are deliberately black holes cut from the coloured body.
    float wheel1=circleMask(p,c+vec2(-carW*0.29,carH*0.31),wheelR);
    float wheel2=circleMask(p,c+vec2( carW*0.29,carH*0.31),wheelR);
    float wheels=max(wheel1,wheel2);
    rgb=mix(rgb,vec3(0.0),wheels);
    alpha=max(alpha,wheels);

    // One small front/rear light each. These should be obvious even at 16px high.
    float lampHalf=max(0.75,H*0.045);
    float head=boxMask(p,c+vec2(dir*carW*0.52,-carH*0.03),vec2(lampHalf,lampHalf));
    float tail=boxMask(p,c-vec2(dir*carW*0.52, carH*0.03),vec2(lampHalf,lampHalf));
    rgb+=HeadlightColor.rgb*head;
    rgb+=TaillightColor.rgb*tail;
    alpha=max(alpha,max(head,tail));
  }

  gl_FragColor=vec4(clamp(rgb,0.0,1.0),clamp(alpha,0.0,1.0));
}
