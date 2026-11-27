/** الكرة ثلاثية الأبعاد ككومبوننت React.
 *
 *  المسؤولية هنا هي العمر فقط: تعمل المشهد لما تفتح، تقرأ الصوت كل فريم، وتقفله لما تقفل.
 *  القرارات البصرية كلها في looks.js، والرسم في voiceOrbScene.js — والاتنين بيتستوا لوحدهم.
 *
 *  المشهد بيتعمل مرة واحدة لكل مكالمة. الحالة بتوصل من `stateRef` جوه حلقة الرسم، مش
 *  كاعتماد في useEffect — وإلا كان كل تغيير حالة هيدمّر المشهد ويبنيه من أول وجديد.
 */
import React from "react";
import { dragDelta, orbLook } from "./looks";

/** هل المتصفح يقدر يرسم WebGL فعلاً؟ في jsdom (الاختبارات) الجواب لا، فبنقع على بديل CSS. */
export function supportsWebgl(doc = typeof document !== "undefined" ? document : undefined) {
  if (!doc?.createElement) return false;
  try {
    const canvas = doc.createElement("canvas");
    const context =
      canvas.getContext("webgl2") || canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    return Boolean(context);
  } catch {
    return false;
  }
}

export function prefersReducedMotion(win = typeof window !== "undefined" ? window : undefined) {
  try {
    return Boolean(win?.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
  } catch {
    return false;
  }
}

/** بديل ثابت لما WebGL مش متاح: نفس اللون ونفس النبض، من غير GPU. */
function OrbFallback({ look }) {
  const color = `hsl(${look.hue} 72% 55%)`;
  return (
    <div
      data-testid="voice-orb-fallback"
      data-mode={look.mode}
      aria-hidden
      className="relative grid h-full w-full place-items-center"
    >
      <div
        className="h-[62%] w-[62%] rounded-full"
        style={{
          background: `radial-gradient(circle at 35% 30%, ${color}, rgba(5,7,13,0.15) 72%)`,
          boxShadow: `0 0 90px 20px ${color}55`,
          opacity: 0.5 + look.glow * 0.5,
        }}
      />
    </div>
  );
}

export default function VoiceOrb({ state = "idle", meter = null, className = "", forceFallback = false }) {
  const hostRef = React.useRef(null);
  const canvasRef = React.useRef(null);
  const stateRef = React.useRef(state);
  stateRef.current = state;

  const [webgl, setWebgl] = React.useState(() => !forceFallback && supportsWebgl());
  const reduced = React.useMemo(() => prefersReducedMotion(), []);
  const staticLook = React.useMemo(() => orbLook({ state, reduced }), [state, reduced]);

  React.useEffect(() => {
    if (!webgl) return undefined;
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return undefined;

    let scene = null;
    let raf = 0;
    let last = 0;
    let alive = true;
    let detach = () => {};

    // الاستيراد متأخر عن قصد: three بيتحمّل مع شاشة المكالمة، مش مع الصفحة كلها.
    import("./voiceOrbScene")
      .then(({ createOrbScene }) => {
        if (!alive) return;
        const rect = host.getBoundingClientRect();
        scene = createOrbScene({
          canvas,
          width: rect.width || 320,
          height: rect.height || 320,
          reducedMotion: reduced,
        });

        const step = (now) => {
          if (!alive) return;
          const delta = last ? (now - last) / 1000 : 0;
          last = now;
          const levels = meter?.read?.() ?? { mic: 0, assistant: 0 };
          const live = orbLook({
            state: stateRef.current,
            mic: levels.mic,
            assistant: levels.assistant,
            reduced,
          });
          scene.setTarget({
            hue: live.hue,
            energy: live.emissive,
            distortion: live.distortion,
            spin: live.spin,
            scale: live.scale,
            glow: live.glow,
          });
          scene.frame(delta);
          raf = requestAnimationFrame(step);
        };
        raf = requestAnimationFrame(step);

        const onResize = () => {
          const box = host.getBoundingClientRect();
          scene?.resize(box.width || 320, box.height || 320);
        };
        // الماوس بيأثر على المشهد من أي مكان في الصفحة، مش على الكانفس بس:
        // التحريك بيلف الكاميرا (parallax)، والسحب بيلفها أكتر ويفضل ماسك لفة لحد ما تسيب.
        let dragging = false;
        let anchor = { x: 0, y: 0 };
        let drag = { x: 0, y: 0 };

        const onPointer = (event) => {
          const box = host.getBoundingClientRect();
          scene?.setPointer(
            ((event.clientX - box.left) / Math.max(1, box.width)) * 2 - 1,
            ((event.clientY - box.top) / Math.max(1, box.height)) * 2 - 1
          );
          if (!dragging) return;
          drag = dragDelta({
            dx: event.clientX - anchor.x,
            dy: event.clientY - anchor.y,
            width: box.width,
            height: box.height,
            current: drag,
          });
          anchor = { x: event.clientX, y: event.clientY };
          scene?.setDrag(drag.x, drag.y);
        };
        const onDown = (event) => {
          dragging = true;
          anchor = { x: event.clientX, y: event.clientY };
        };
        const onUp = () => {
          dragging = false;
          drag = { x: 0, y: 0 };
          scene?.releaseDrag();
        };

        window.addEventListener("resize", onResize);
        window.addEventListener("pointermove", onPointer);
        window.addEventListener("pointerdown", onDown);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onUp);
        detach = () => {
          window.removeEventListener("resize", onResize);
          window.removeEventListener("pointermove", onPointer);
          window.removeEventListener("pointerdown", onDown);
          window.removeEventListener("pointerup", onUp);
          window.removeEventListener("pointercancel", onUp);
        };
      })
      .catch(() => {
        // مشكلة في تحميل three أو في سياق WebGL: بنقع على البديل بدل شاشة فاضية.
        if (alive) setWebgl(false);
      });

    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      detach();
      scene?.dispose();
      scene = null;
    };
  }, [webgl, meter, reduced]);

  return (
    <div ref={hostRef} className={`relative ${className}`} data-testid="voice-orb" data-mode={staticLook.mode}>
      {webgl ? <canvas ref={canvasRef} className="h-full w-full" aria-hidden /> : <OrbFallback look={staticLook} />}
    </div>
  );
}
