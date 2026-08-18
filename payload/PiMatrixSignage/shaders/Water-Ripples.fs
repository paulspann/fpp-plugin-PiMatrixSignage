/*{
  "TITLE":"Water Ripples",
  "DESCRIPTION":"Animated low-resolution water surface with gentle waves, ripples and pool shimmer modes.",
  "CREDIT":"Pi Matrix Signage",
  "CATEGORIES":["Built-in","Water","Generator"],
  "INPUTS":[
    {"NAME":"Style","LABEL":"Style","TYPE":"long","DEFAULT":0,"VALUES":[0,1,2],"LABELS":["Gentle water","Ripples","Pool shimmer"]},
    {"NAME":"Speed","LABEL":"Speed","TYPE":"float","DEFAULT":1.0,"MIN":0.05,"MAX":4.0},
    {"NAME":"WaveHeight","LABEL":"Wave height","TYPE":"float","DEFAULT":1.8,"MIN":0.2,"MAX":6.0},
    {"NAME":"RippleSize","LABEL":"Ripple size","TYPE":"float","DEFAULT":12.0,"MIN":3.0,"MAX":40.0},
    {"NAME":"Choppiness","LABEL":"Choppiness","TYPE":"float","DEFAULT":0.35,"MIN":0.0,"MAX":1.0},
    {"NAME":"WaterColor","LABEL":"Water colour","TYPE":"color","DEFAULT":[0.5686,0.7922,0.8392,1.0]},
    {"NAME":"DeepColor","LABEL":"Deep water colour","TYPE":"color","DEFAULT":[0.0,0.2157,0.2824,1.0]},
    {"NAME":"HighlightColor","LABEL":"Highlight colour","TYPE":"color","DEFAULT":[0.92,0.98,1.0,1.0]},
    {"NAME":"WaterOpacity","LABEL":"Opacity","TYPE":"float","DEFAULT":0.82,"MIN":0.05,"MAX":1.0}
  ],
  "ISFVSN":"2"
}*/

float hash1(float n) {
  return fract(sin(n * 91.3458) * 47453.5453);
}

float softLine(float d, float width) {
  return 1.0 - smoothstep(width, width + 0.8, abs(d));
}

void main() {
  vec2 p = gl_FragCoord.xy;
  float w = max(RENDERSIZE.x, 1.0);
  float h = max(RENDERSIZE.y, 1.0);
  float t = TIME * Speed;
  float chop = clamp(Choppiness, 0.0, 1.0);
  float size = max(RippleSize, 1.0);

  /* A moving water surface measured upward from the bottom of the layer. */
  float waveA = sin((p.x / size) * 2.15 + t * 2.1);
  float waveB = sin((p.x / (size * 0.61)) * 1.35 - t * 1.47 + 1.2);
  float waveC = sin((p.x / (size * 1.73)) * 3.0 + t * 0.72 + 2.4);
  float surface = h - 1.35 - WaveHeight * (0.55 * waveA + 0.28 * waveB * chop + 0.17 * waveC * chop);

  /* Fill below the surface only, leaving the area above transparent. */
  float waterMask = 1.0 - smoothstep(surface - 0.25, surface + 0.75, p.y);
  float depth = clamp((surface - p.y) / max(h, 1.0), 0.0, 1.0);
  vec3 base = mix(WaterColor.rgb, DeepColor.rgb, clamp(depth * 1.55, 0.0, 1.0));

  float surfaceGlow = softLine(p.y - surface, 0.45);
  float shimmer = 0.0;

  if (Style == 0) {
    /* Gentle water: broad travelling bands and a restrained surface highlight. */
    float band1 = sin(p.x / max(size * 0.75, 1.0) + p.y * 0.82 + t * 1.7);
    float band2 = sin(p.x / max(size * 0.44, 1.0) - p.y * 1.23 - t * 1.12);
    shimmer = pow(max(0.0, 0.5 + 0.5 * (band1 * 0.66 + band2 * 0.34)), 5.0) * 0.32;
  } else if (Style == 1) {
    /* Ripples: two moving ring sources, softened for very low-resolution LED strips. */
    vec2 c1 = vec2(mod(t * 12.0, w + size * 2.0) - size, h * 0.52);
    vec2 c2 = vec2(w - mod(t * 8.4 + w * 0.37, w + size * 2.0) + size, h * 0.25);
    float d1 = distance(p, c1);
    float d2 = distance(p, c2);
    float r1 = 0.5 + 0.5 * sin(d1 * (6.28318 / size) - t * 3.5);
    float r2 = 0.5 + 0.5 * sin(d2 * (6.28318 / max(size * 0.82, 1.0)) - t * 2.8 + 1.7);
    float fade1 = 1.0 / (1.0 + d1 * 0.055);
    float fade2 = 1.0 / (1.0 + d2 * 0.055);
    shimmer = pow(max(r1 * fade1, r2 * fade2), 3.0) * (0.45 + chop * 0.35);
  } else {
    /* Pool shimmer: small moving caustic streaks under the water surface. */
    float u = p.x / max(size * 0.48, 1.0);
    float v = p.y / max(size * 0.32, 1.0);
    float a = sin(u + sin(v * 1.7 - t * 1.2) + t * 1.8);
    float b = sin(v * 1.35 + sin(u * 1.4 + t) - t * 1.45);
    float c = sin((u + v) * 0.8 - t * 0.7);
    float caustic = abs(a + b + c) / 3.0;
    shimmer = pow(1.0 - clamp(caustic, 0.0, 1.0), 4.5) * 0.95;
  }

  /* Keep highlights strongest near the top but allow a little movement underneath. */
  float nearSurface = 1.0 - clamp(depth * 1.8, 0.0, 1.0);
  float highlightAmount = clamp(surfaceGlow * 0.85 + shimmer * (0.35 + nearSurface * 0.65), 0.0, 1.0);
  vec3 col = mix(base, HighlightColor.rgb, highlightAmount);

  /* A subtle pixel-scale sparkle gives P5/P10 strips movement without visual noise. */
  float sparkle = hash1(floor(p.x) + floor(p.y) * 131.0 + floor(t * 2.0) * 17.0);
  if (sparkle > 0.985 && nearSurface > 0.45) {
    col = mix(col, HighlightColor.rgb, 0.35 * chop);
  }

  gl_FragColor = vec4(col, waterMask * clamp(WaterOpacity, 0.0, 1.0));
}
