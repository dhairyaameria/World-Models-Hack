"use client";

import type { Heard } from "@/lib/contract";
import type { AudioSourceState } from "@/lib/audioScene";

const SIZE = 190;
const R = SIZE / 2 - 12;
const MAX_M = 15;

const ICON: [RegExp, string][] = [
  [/hiss|gas/i, "💨"],
  [/creak|crack|struct/i, "🏚"],
  [/water|flood/i, "🌊"],
  [/fire|crackl/i, "🔥"],
  [/alarm|siren/i, "🚨"],
  [/tap|knock/i, "🔨"],
  [/tv|radio|broadcast|news/i, "📺"],
  [/warn|don't come|collapsed/i, "⚠️"],
  [/voice|help|cry|call|child|person|survivor|shout/i, "🗣"],
];

function icon(label: string) {
  return ICON.find(([re]) => re.test(label))?.[1] ?? "🔊";
}

function xy(bearing: number, dist: number) {
  const r = (Math.min(dist, MAX_M) / MAX_M) * R;
  const b = (bearing * Math.PI) / 180;
  return [SIZE / 2 + Math.sin(b) * r, SIZE / 2 - Math.cos(b) * r];
}

/** What the robot hears. Forward is up. Blips = the model's interpretation at mic-array estimates;
 *  hollow rings (operator toggle) = ground truth, to show mic-array error. */
export function AudioRadar({ heard, truth, showTruth, hearingOn }: {
  heard: Heard[];
  truth: AudioSourceState[];
  showTruth: boolean;
  hearingOn: boolean;
}) {
  const audible = truth.filter((s) => s.playing && s.gain > 0.04);
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 rounded-full bg-black/60" style={{ width: SIZE, height: SIZE }}>
      <svg width={SIZE} height={SIZE}>
        {[1, 2, 3].map((i) => (
          <circle key={i} cx={SIZE / 2} cy={SIZE / 2} r={(R * i) / 3} fill="none" stroke="#334155" strokeDasharray={i < 3 ? "3 4" : undefined} />
        ))}
        <line x1={SIZE / 2} y1={12} x2={SIZE / 2} y2={SIZE / 2} stroke="#475569" />
        <polygon points={`${SIZE / 2},${SIZE / 2 - 7} ${SIZE / 2 - 5},${SIZE / 2 + 5} ${SIZE / 2 + 5},${SIZE / 2 + 5}`} fill="#f8fafc" />
        {showTruth && audible.map((s) => {
          const [x, y] = xy(s.bearing_deg, s.distance_m);
          return <circle key={`t-${s.id}`} cx={x} cy={y} r={9} fill="none" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="2 2" />;
        })}
        {heard.map((h, i) => {
          const [x, y] = xy(h.bearing_deg, h.distance_m);
          const color = h.is_decoy_suspected ? "#94a3b8" : h.is_hazard ? (h.urgency >= 3 ? "#ef4444" : "#f59e0b") : "#22c55e";
          return (
            <g key={`h-${h.source_id ?? i}`}>
              <circle cx={x} cy={y} r={13} fill={color} opacity={0.25}>
                <animate attributeName="r" values="10;16;10" dur="1.4s" repeatCount="indefinite" />
              </circle>
              <circle cx={x} cy={y} r={9} fill={color} opacity={0.9} />
              <text x={x} y={y + 4} textAnchor="middle" fontSize="11">{icon(h.label)}</text>
            </g>
          );
        })}
      </svg>
      <div className="absolute -top-6 left-0 w-full text-center font-mono text-[11px] uppercase tracking-wide text-slate-300">
        {hearingOn ? `Hearing · ${heard.length} source${heard.length === 1 ? "" : "s"}` : "Hearing off"}
      </div>
    </div>
  );
}
