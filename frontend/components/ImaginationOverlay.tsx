"use client";

import type { ForkStatus, ImagineOption } from "@/lib/imagine";

export interface ImagineScore {
  id: string;
  risk: number;
  progress: number;
  summary: string;
}

export interface ImaginationView {
  requestId: string;
  options: ImagineOption[];
  status: Record<string, ForkStatus>;
  tiles: Record<string, HTMLVideoElement | HTMLCanvasElement>;
  frames?: Record<string, string[]>; // captured frames per fork (kept after the fork session ends)
  verdict?: { scores: ImagineScore[]; chosen_id: string; reason: string };
}

const STATUS_TEXT: Record<ForkStatus, string> = {
  starting: "forking world from current frame…",
  simulating: "simulating maneuver…",
  done: "outcome captured",
  failed: "simulation failed",
};

function Bar({ value, color }: { value: number; color: string }) {
  return (
    <div className="h-2 w-full rounded bg-slate-700">
      <div className={`h-2 rounded ${color}`} style={{ width: `${Math.max(0, Math.min(10, value)) * 10}%` }} />
    </div>
  );
}

/** Full-screen "IMAGINING" moment: one live tile per imagined future, then scores + the choice. */
export function ImaginationOverlay({ view }: { view: ImaginationView }) {
  const v = view.verdict;
  return (
    <div className="absolute inset-0 z-10 flex flex-col bg-slate-950/85 p-4">
      <div className="mb-3 text-center">
        <div className="text-2xl font-bold tracking-widest text-sky-300">
          {v ? "IMAGINED FUTURES · DECISION" : "IMAGINING POSSIBLE FUTURES…"}
        </div>
        <div className="text-sm text-slate-400">
          {v ? v.reason : "The world model is forked from the robot's current view; each fork runs one maneuver."}
        </div>
      </div>
      <div className="grid flex-1 grid-cols-3 gap-3">
        {view.options.map((o) => {
          const s = v?.scores.find((x) => x.id === o.id);
          const chosen = v?.chosen_id === o.id;
          return (
            <div key={o.id}
              className={`flex flex-col overflow-hidden rounded-lg border-2 ${chosen ? "border-green-400" : v ? "border-slate-700 opacity-60" : "border-sky-700"}`}>
              <div className="flex items-center justify-between bg-slate-900 px-2 py-1 text-sm font-semibold">
                <span>{o.label}</span>
                {chosen && <span className="rounded bg-green-500 px-2 text-xs text-black">CHOSEN</span>}
                {v && !chosen && <span className="text-red-400">✗</span>}
              </div>
              {(() => {
                const frames = view.frames?.[o.id] ?? [];
                const done = view.status[o.id] === "done" || view.status[o.id] === "failed" || !!v;
                if (done && frames.length) {
                  return (
                    <div className="bg-black">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img alt="imagined outcome" className="aspect-video w-full object-cover" src={`data:image/jpeg;base64,${frames[frames.length - 1]}`} />
                      <div className="flex gap-1 p-1">
                        {frames.map((f, i) => (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img key={i} alt={`step ${i + 1}`} className="h-10 flex-1 rounded object-cover opacity-80" src={`data:image/jpeg;base64,${f}`} />
                        ))}
                      </div>
                    </div>
                  );
                }
                return (
                  <div className="relative aspect-video bg-black"
                    ref={(el) => {
                      const tile = view.tiles[o.id];
                      if (el && tile && el.firstChild !== tile) el.replaceChildren(tile);
                    }} />
                );
              })()}
              <div className="flex-1 space-y-1 bg-slate-900 p-2 text-xs">
                {!s && <div className="text-slate-400">{STATUS_TEXT[view.status[o.id] ?? "starting"]}</div>}
                {s && (
                  <>
                    <div className="flex items-center gap-2"><span className="w-16 text-green-300">progress</span><Bar value={s.progress} color="bg-green-500" /><span>{s.progress.toFixed(0)}</span></div>
                    <div className="flex items-center gap-2"><span className="w-16 text-red-300">risk</span><Bar value={s.risk} color="bg-red-500" /><span>{s.risk.toFixed(0)}</span></div>
                    <div className="pt-1 text-slate-300">{s.summary}</div>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
