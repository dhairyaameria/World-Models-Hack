"use client";

import { useEffect, useRef } from "react";
import type { Decision, Pose } from "@/lib/contract";

const MARKER_FADE_MS = 1500;
const ARROWS: Record<string, string> = { W: "↑", S: "↓", A: "←", D: "→" };
const LOOK_ARROWS: Record<string, string> = { left: "↶", right: "↷", up: "⤒", down: "⤓" };

interface Props {
  decision: Decision | null;
  receivedAt: number;
  trail: Pose[];
  stats: { steps: number; survivors: number; hazardsAvoided: number; elapsedS: number };
}

/** Canvas overlay drawn on top of the world video. Coordinates are [y, x] in 0-1000. */
export function HudOverlay({ decision, receivedAt, trail, stats }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let raf = 0;
    const draw = () => {
      const c = ref.current;
      if (!c) return;
      const { clientWidth: W, clientHeight: H } = c;
      if (c.width !== W || c.height !== H) {
        c.width = W;
        c.height = H;
      }
      const ctx = c.getContext("2d")!;
      ctx.clearRect(0, 0, W, H);
      const age = performance.now() - receivedAt;
      const alpha = Math.max(0, 1 - age / MARKER_FADE_MS);
      const px = ([y, x]: [number, number]) => [(x / 1000) * W, (y / 1000) * H] as const;

      if (decision && alpha > 0) {
        ctx.globalAlpha = alpha;
        for (const s of decision.survivors) {
          const [x, y] = px(s.point);
          const pulse = 18 + 6 * Math.sin(performance.now() / 150);
          ctx.strokeStyle = "#22c55e";
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.arc(x, y, pulse, 0, Math.PI * 2);
          ctx.stroke();
          label(ctx, s.label, x + 26, y, "#22c55e");
        }
        for (const h of decision.hazards) {
          const [x, y] = px(h.point);
          const color = h.severity === 3 ? "#ef4444" : "#f59e0b";
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.moveTo(x, y - 18);
          ctx.lineTo(x + 16, y + 12);
          ctx.lineTo(x - 16, y + 12);
          ctx.closePath();
          ctx.fill();
          ctx.fillStyle = "#000";
          ctx.font = "bold 16px sans-serif";
          ctx.fillText("!", x - 3, y + 8);
          label(ctx, `${h.label} (sev ${h.severity})`, x + 22, y, color);
        }
        ctx.globalAlpha = 1;
      }

      if (decision?.safety_override && age < 2000) {
        ctx.strokeStyle = `rgba(239,68,68,${0.6 + 0.4 * Math.sin(performance.now() / 80)})`;
        ctx.lineWidth = 10;
        ctx.strokeRect(5, 5, W - 10, H - 10);
        ctx.font = "bold 20px sans-serif";
        const text = `SAFETY OVERRIDE: ${decision.safety_override}`;
        const tw = ctx.measureText(text).width;
        ctx.fillStyle = "#dc2626";
        ctx.fillRect(W / 2 - tw / 2 - 14, 52, tw + 28, 36);
        ctx.fillStyle = "#fff";
        ctx.fillText(text, W / 2 - tw / 2, 77);
      }

      drawMinimap(ctx, trail, W, H);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [decision, receivedAt, trail]);

  const a = decision?.action;
  const glyph = a ? ARROWS[a.move] ?? LOOK_ARROWS[a.look] ?? "•" : "";

  return (
    <div className="pointer-events-none absolute inset-0">
      <canvas ref={ref} className="absolute inset-0 h-full w-full" />

      <div className="absolute left-3 top-3 rounded bg-black/60 px-3 py-2 font-mono text-sm text-slate-200">
        <div>STEPS {stats.steps}</div>
        <div className="text-green-400">SURVIVORS {stats.survivors}</div>
        <div className="text-amber-400">HAZARDS AVOIDED {stats.hazardsAvoided}</div>
        <div>T+{stats.elapsedS.toFixed(0)}s</div>
      </div>

      {decision?.exit_seen && (
        <div className="absolute right-3 top-3 rounded bg-green-600/90 px-4 py-1 text-xl font-bold text-white">EXIT</div>
      )}

      {decision && (
        <div className="absolute bottom-4 left-1/2 flex max-w-[80%] -translate-x-1/2 items-center gap-3 rounded bg-black/70 px-4 py-2 text-white">
          <span className="text-3xl">{glyph}</span>
          <div>
            <div className="text-lg leading-tight">{decision.reason}</div>
            {decision.priority && <div className="text-xs uppercase text-slate-400">Priority: {decision.priority}</div>}
          </div>
          <span className="ml-2 rounded bg-slate-700 px-2 py-0.5 font-mono text-xs">
            {decision.source} · {Math.round(decision.latency_ms)} ms
          </span>
        </div>
      )}
    </div>
  );
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string) {
  ctx.font = "bold 15px sans-serif";
  const w = ctx.measureText(text).width;
  ctx.fillStyle = "rgba(0,0,0,0.7)";
  ctx.fillRect(x - 4, y - 14, w + 8, 20);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y + 1);
}

function drawMinimap(ctx: CanvasRenderingContext2D, trail: Pose[], W: number, H: number) {
  const size = 160;
  const ox = W - size - 12;
  const oy = H - size - 12;
  ctx.fillStyle = "rgba(0,0,0,0.6)";
  ctx.fillRect(ox, oy, size, size);
  ctx.strokeStyle = "#475569";
  ctx.strokeRect(ox, oy, size, size);
  if (trail.length === 0) return;
  const last = trail[trail.length - 1];
  const scale = 6; // px per meter, centered on the robot
  const toPx = (p: Pose) => [ox + size / 2 + (p.x - last.x) * scale, oy + size / 2 - (p.y - last.y) * scale];
  ctx.strokeStyle = "#38bdf8";
  ctx.lineWidth = 2;
  ctx.beginPath();
  trail.forEach((p, i) => {
    const [x, y] = toPx(p);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  const [cx, cy] = toPx(last);
  const h = (last.heading_deg * Math.PI) / 180;
  ctx.fillStyle = "#f8fafc";
  ctx.beginPath();
  ctx.moveTo(cx + Math.sin(h) * 9, cy - Math.cos(h) * 9);
  ctx.lineTo(cx + Math.sin(h + 2.5) * 6, cy - Math.cos(h + 2.5) * 6);
  ctx.lineTo(cx + Math.sin(h - 2.5) * 6, cy - Math.cos(h - 2.5) * 6);
  ctx.fill();
}
