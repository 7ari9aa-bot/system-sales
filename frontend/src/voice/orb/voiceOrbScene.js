/** مشهد الكرة ثلاثي الأبعاد: كرة سائلة بتنوّر وتتنفّس مع الصوت.
 *
 *  three.js مباشرة من غير react-three-fiber — المشهد كله أوبجكت واحد بيتعمل مرة واحدة
 *  وبيتحدّث كل فريم، والـreconciler مش بيضيف حاجة هنا غير وزن.
 *
 *  المشهد مفصول عن React عشان يقدر يتقفل ويتعمل من جديد مع كل مكالمة، ولأن الكرة بتقرأ
 *  الأرقام من عدّاد خارجي كل فريم بدل ما تعيد الرسم مع كل حزمة صوت.
 */
import * as THREE from "three";

const VERT = /* glsl */ `
  uniform float uTime;
  uniform float uEnergy;
  uniform float uDistortion;
  varying vec3 vNormal;
  varying vec3 vView;
  varying float vWave;

  // ضجيج رخيص: موجات جيبية بترددات متداخلة. مش simplex حقيقي، لكن على كرة بيدور
  // النتيجة سائلة ومش متكررة بالعين، وتكلفتها صفر تقريباً على GPU الموبايل.
  float wave(vec3 p, float t) {
    float w = sin(p.x * 2.1 + t) * 0.5;
    w += sin(p.y * 2.7 - t * 1.3) * 0.35;
    w += sin(p.z * 3.3 + t * 0.7) * 0.25;
    w += sin((p.x + p.y + p.z) * 5.1 - t * 2.1) * 0.12;
    return w;
  }

  void main() {
    vec3 p = normalize(position);
    float w = wave(p, uTime);
    vWave = w;
    float offset = w * (uDistortion * 0.45 + uEnergy * 0.12);
    vec3 displaced = position + normal * offset;

    vNormal = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(displaced, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

const FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform vec3 uCore;
  uniform float uEnergy;
  uniform float uTime;
  varying vec3 vNormal;
  varying vec3 vView;
  varying float vWave;

  void main() {
    float fresnel = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.4);
    float veins = smoothstep(0.25, 1.0, vWave * 0.5 + 0.5);
    float pulse = 0.5 + 0.5 * sin(uTime * 2.0);

    vec3 color = mix(uCore, uColor, 0.35 + fresnel * 0.65);
    color += uColor * veins * (0.18 + uEnergy * 0.5);
    color += vec3(1.0) * fresnel * (0.25 + uEnergy * 0.55);
    color += uColor * pulse * uEnergy * 0.12;

    gl_FragColor = vec4(color, 1.0);
  }
`;

const GLOW_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  varying vec2 vUv;

  void main() {
    float d = distance(vUv, vec2(0.5));
    float falloff = smoothstep(0.5, 0.0, d);
    gl_FragColor = vec4(uColor, falloff * falloff * uOpacity);
  }
`;

const GLOW_VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

function hsl(hue) {
  const color = new THREE.Color();
  color.setHSL((hue % 360) / 360, 0.72, 0.55);
  return color;
}

function coreColor(hue) {
  const color = new THREE.Color();
  color.setHSL(((hue + 26) % 360) / 360, 0.5, 0.72);
  return color;
}

function buildHalo() {
  const count = 900;
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i += 1) {
    // توزيع على قشرة كروية بسمك بسيط: حبيبات ضوء حوالين الكرة.
    const u = Math.random();
    const v = Math.random();
    const theta = 2 * Math.PI * u;
    const phi = Math.acos(2 * v - 1);
    const radius = 1.45 + Math.random() * 0.5;
    positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = radius * Math.cos(phi);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    size: 0.022,
    transparent: true,
    opacity: 0.55,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  return new THREE.Points(geometry, material);
}

/** يبني المشهد جوه عنصر موجود. بيرجع متحكم بيتنادى عليه من حلقة الرسم. */
export function createOrbScene({ canvas, width, height, reducedMotion = false }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, Math.max(1, globalThis.devicePixelRatio || 1)));
  renderer.setSize(width, height, false);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, width / Math.max(1, height), 0.1, 100);
  camera.position.set(0, 0, 3.4);

  const uniforms = {
    uTime: { value: 0 },
    uEnergy: { value: 0 },
    uDistortion: { value: 0.06 },
    uColor: { value: hsl(158) },
    uCore: { value: coreColor(158) },
  };

  const orb = new THREE.Mesh(
    new THREE.SphereGeometry(1, 160, 160),
    new THREE.ShaderMaterial({ uniforms, vertexShader: VERT, fragmentShader: FRAG })
  );
  scene.add(orb);

  const shell = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.42, 1),
    new THREE.MeshBasicMaterial({ wireframe: true, transparent: true, opacity: 0.12, color: hsl(170) })
  );
  scene.add(shell);

  const halo = buildHalo();
  halo.material.color = hsl(168);
  scene.add(halo);

  const glowUniforms = { uColor: { value: hsl(160) }, uOpacity: { value: 0.35 } };
  const glow = new THREE.Mesh(
    new THREE.PlaneGeometry(7, 7),
    new THREE.ShaderMaterial({
      uniforms: glowUniforms,
      vertexShader: GLOW_VERT,
      fragmentShader: GLOW_FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
  );
  glow.position.z = -1.2;
  scene.add(glow);

  const state = {
    time: 0,
    energy: 0,
    hue: 158,
    distortion: 0.06,
    spin: 0.1,
    scale: 1,
    glow: 0.35,
    pointer: { x: 0, y: 0 },
    disposed: false,
  };

  return {
    /** تحديث الهدف من الحالة والصوت؛ الحركة نفسها بتتدرّج في `frame`. */
    setTarget({ hue, energy, distortion, spin, scale, glow: glowValue }) {
      if (Number.isFinite(hue)) state.hue = hue;
      if (Number.isFinite(energy)) state.energy = energy;
      if (Number.isFinite(distortion)) state.distortion = distortion;
      if (Number.isFinite(spin)) state.spin = spin;
      if (Number.isFinite(scale)) state.scale = scale;
      if (Number.isFinite(glowValue)) state.glow = glowValue;
    },

    setPointer(x, y) {
      state.pointer.x = Math.max(-1, Math.min(1, x));
      state.pointer.y = Math.max(-1, Math.min(1, y));
    },

    resize(nextWidth, nextHeight) {
      renderer.setSize(nextWidth, nextHeight, false);
      camera.aspect = nextWidth / Math.max(1, nextHeight);
      camera.updateProjectionMatrix();
    },

    /** فريم واحد. `delta` بالثواني عشان الحركة تبقى نفسها على 60 و120 هرتز. */
    frame(delta) {
      const dt = Math.min(0.05, Math.max(0, delta || 0));
      if (reducedMotion) state.spin = 0;
      state.time += dt;

      uniforms.uTime.value = state.time;
      uniforms.uEnergy.value += (state.energy - uniforms.uEnergy.value) * 0.12;
      uniforms.uDistortion.value += (state.distortion - uniforms.uDistortion.value) * 0.1;
      uniforms.uColor.value.lerp(hsl(state.hue), 0.06);
      uniforms.uCore.value.lerp(coreColor(state.hue), 0.06);

      const targetScale = state.scale + uniforms.uEnergy.value * 0.06;
      orb.scale.setScalar(orb.scale.x + (targetScale - orb.scale.x) * 0.1);

      orb.rotation.y += state.spin * dt;
      orb.rotation.x = Math.sin(state.time * 0.35) * 0.06 + state.pointer.y * 0.12;
      orb.rotation.z = state.pointer.x * 0.08;

      shell.rotation.y -= state.spin * dt * 0.6;
      shell.rotation.x += state.spin * dt * 0.25;
      shell.material.opacity = 0.08 + uniforms.uEnergy.value * 0.22;
      shell.material.color.lerp(hsl(state.hue), 0.05);

      halo.rotation.y += dt * (0.05 + state.spin * 0.4);
      halo.material.color.lerp(hsl(state.hue), 0.05);
      halo.material.opacity = 0.35 + uniforms.uEnergy.value * 0.5;
      halo.material.size = 0.018 + uniforms.uEnergy.value * 0.02;

      glowUniforms.uColor.value.lerp(hsl(state.hue), 0.05);
      glowUniforms.uOpacity.value += (state.glow * 0.55 - glowUniforms.uOpacity.value) * 0.08;

      renderer.render(scene, camera);
    },

    dispose() {
      if (state.disposed) return;
      state.disposed = true;
      orb.geometry.dispose();
      orb.material.dispose();
      shell.geometry.dispose();
      shell.material.dispose();
      halo.geometry.dispose();
      halo.material.dispose();
      glow.geometry.dispose();
      glow.material.dispose();
      renderer.dispose();
    },
  };
}
