"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { HudOverlay } from "@/components/HudOverlay";
import { BackendClient } from "@/lib/backend";
import { BACKEND_HTTP, type Decision, type Mode, type Pose, type Scenario } from "@/lib/contract";
import { ReactorWorld, StaticWorld, type World } from "@/lib/world";

const FRAME_INTERVAL_MS = Number(process.env.NEXT_PUBLIC_FRAME_INTERVAL_MS ?? 500);
type WorldKind = "static" | "reactor";
type LogEntry = { id: number; t: number; text: string; override?: string | null; thumb?: string | null };

export default function MissionControl() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const [worldKind, setWorldKind] = useState<WorldKind>(
    process.env.NEXT_PUBLIC_DEFAULT_WORLD === "reactor" ? "reactor" : "static",
  );
  const [mode, setMode] = useState<Mode>("autopilot");
  const [hearing, setHearing] = useState(false);

  const [connected, setConnected] = useState(false);
  const [worldStatus, setWorldStatus] = useState("idle");
  const [episodeId, setEpisodeId] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [receivedAt, setReceivedAt] = useState(0);
  const [trail, setTrail] = useState<Pose[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState({ steps: 0, survivors: 0, hazardsAvoided: 0, elapsedS: 0 });
  const [tab, setTab] = useState<"log" | "imagination" | "episodes">("log");

  const backend = useRef<BackendClient | null>(null);
  const world = useRef<World | null>(null);
  const videoHost = useRef<HTMLDivElement>(null);
  const episodeRef = useRef<string | null>(null);
  const startedAt = useRef(0);
  const lastThumb = useRef<string | null>(null);
  const logId = useRef(0);

  useEffect(() => {
    fetch(`${BACKEND_HTTP}/scenarios`)
      .then((r) => r.json())
      .then((s: Scenario[]) => {
        setScenarios(s);
        setScenarioId((cur) => cur || s[0]?.id || "");
      })
      .catch(() => setError(`Backend not reachable at ${BACKEND_HTTP}. Is uvicorn running?`));

    const client = new BackendClient();
    client.onConnection = setConnected;
    client.connect();
    backend.current = client;
    return () => client.close();
  }, []);

  const handleDecision = useCallback((d: Decision) => {
    if (d.episode_id !== episodeRef.current) return;
    world.current?.sendAction(d.action);
    setDecision(d);
    setReceivedAt(performance.now());
    setTrail((t) => [...t.slice(-500), d.pose]);
    setStats((s) => ({
      ...s,
      steps: s.steps + 1,
      survivors: s.survivors + d.survivors.length,
      hazardsAvoided: s.hazardsAvoided + (d.safety_override || (d.hazards.length && d.action.move !== "W") ? 1 : 0),
    }));
    const entry = { id: logId.current++, t: Date.now(), text: d.reason, override: d.safety_override, thumb: lastThumb.current };
    setLog((l) => [entry, ...l].slice(0, 200));
  }, []);

  useEffect(() => {
    const client = backend.current;
    if (!client) return;
    return client.subscribe((msg) => {
      if (msg.type === "decision") handleDecision(msg);
      else if (msg.type === "director_event" && msg.episode_id === episodeRef.current) {
        void world.current?.setPrompt(msg.world_prompt);
        setBanner(msg.caption);
        setTimeout(() => setBanner(null), 4000);
      } else if (msg.type === "error") setError(msg.message);
    });
  }, [handleDecision, connected]);

  // Frame loop: capture -> backend while an episode runs.
  useEffect(() => {
    if (!episodeId) return;
    const id = setInterval(() => {
      const jpeg = world.current?.captureFrame();
      setStats((s) => ({ ...s, elapsedS: (performance.now() - startedAt.current) / 1000 }));
      if (!jpeg) return;
      lastThumb.current = jpeg;
      backend.current?.send({ type: "frame", episode_id: episodeId, ts: Date.now() / 1000, jpeg_b64: jpeg });
    }, FRAME_INTERVAL_MS);
    return () => clearInterval(id);
  }, [episodeId]);

  async function start() {
    const scenario = scenarios.find((s) => s.id === scenarioId);
    const client = backend.current;
    if (!scenario || !client) return;
    setError(null);

    const w: World = worldKind === "reactor" ? new ReactorWorld() : new StaticWorld();
    w.onStatus = setWorldStatus;
    world.current = w;
    w.video.className = "h-full w-full object-cover";
    videoHost.current?.replaceChildren(w.video);
    try {
      await w.start(`${BACKEND_HTTP}${scenario.reference_image_url}`, scenario.world_prompt);
    } catch (e) {
      setError(`World failed to start: ${(e as Error).message}`);
      return;
    }

    const started = await new Promise<string>((resolve) => {
      const off = client.subscribe((msg) => {
        if (msg.type === "episode_started") {
          off();
          resolve(msg.episode_id);
        }
      });
      client.send({ type: "start_episode", scenario_id: scenario.id, mode, agent: "cloud", imagination: false, hearing });
    });
    episodeRef.current = started;
    startedAt.current = performance.now();
    setStats({ steps: 0, survivors: 0, hazardsAvoided: 0, elapsedS: 0 });
    setTrail([{ x: 0, y: 0, heading_deg: 0 }]);
    setLog([]);
    setDecision(null);
    setEpisodeId(started);
  }

  async function stop(outcome: "timeout" | "escaped" | "failed" = "timeout") {
    if (episodeId) backend.current?.send({ type: "end_episode", episode_id: episodeId, outcome });
    episodeRef.current = null;
    setEpisodeId(null);
    await world.current?.stop();
    setWorldStatus("idle");
  }

  async function triggerEvent() {
    if (!episodeId) return;
    await fetch(`${BACKEND_HTTP}/director/trigger`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_ids: [episodeId] }),
    });
  }

  const running = episodeId !== null;

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-100">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-4 py-2">
        <h1 className="mr-4 text-xl font-bold tracking-wide text-amber-400">RESCUESIM · MISSION CONTROL</h1>
        <select className="rounded bg-slate-800 px-2 py-1" value={scenarioId} disabled={running}
          onChange={(e) => setScenarioId(e.target.value)}>
          {scenarios.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
        </select>
        <select className="rounded bg-slate-800 px-2 py-1" value={mode} disabled={running}
          onChange={(e) => setMode(e.target.value as Mode)}>
          <option value="autopilot">Autopilot</option>
          <option value="survivor" disabled>Survivor (P8)</option>
        </select>
        <select className="rounded bg-slate-800 px-2 py-1" value={worldKind} disabled={running}
          onChange={(e) => setWorldKind(e.target.value as WorldKind)}>
          <option value="static">World: Static (free)</option>
          <option value="reactor">World: Reactor (~$0.42/min)</option>
        </select>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={hearing} disabled={running} onChange={(e) => setHearing(e.target.checked)} />
          Hearing
        </label>
        {!running ? (
          <button className="rounded bg-green-600 px-4 py-1 font-semibold hover:bg-green-500 disabled:opacity-40"
            disabled={!connected || !scenarioId} onClick={start}>Start</button>
        ) : (
          <>
            <button className="rounded bg-red-600 px-4 py-1 font-semibold hover:bg-red-500" onClick={() => stop()}>Stop</button>
            <button className="rounded bg-amber-600 px-3 py-1 text-sm hover:bg-amber-500" onClick={triggerEvent}>Disaster event</button>
          </>
        )}
        <div className="ml-auto flex items-center gap-3 font-mono text-xs">
          <span className={connected ? "text-green-400" : "text-red-400"}>● backend {connected ? "online" : "offline"}</span>
          <span className="text-slate-400">world: {worldStatus}</span>
        </div>
      </header>

      {error && <div className="bg-red-900/70 px-4 py-1 text-sm">{error}</div>}

      <main className="flex min-h-0 flex-1">
        <section className="relative w-[65%] bg-black">
          <div ref={videoHost} className="absolute inset-0" />
          {!running && (
            <div className="absolute inset-0 flex items-center justify-center text-slate-500">
              Pick a scenario and press Start
            </div>
          )}
          {running && <HudOverlay decision={decision} receivedAt={receivedAt} trail={trail} stats={stats} />}
          {banner && (
            <div className="absolute left-0 right-0 top-1/3 bg-red-700/90 py-3 text-center text-2xl font-bold tracking-wide">
              ⚠ {banner}
            </div>
          )}
        </section>

        <aside className="flex w-[35%] flex-col border-l border-slate-800">
          <nav className="flex border-b border-slate-800 text-sm">
            {(["log", "imagination", "episodes"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`flex-1 py-2 uppercase tracking-wide ${tab === t ? "bg-slate-800 text-amber-400" : "text-slate-400"}`}>
                {t === "log" ? "Agent log" : t}
              </button>
            ))}
          </nav>
          <div className="flex-1 overflow-y-auto p-3 text-sm">
            {tab === "log" && (log.length === 0
              ? <p className="text-slate-500">Decisions appear here.</p>
              : log.map((e) => (
                <details key={e.id} className={`mb-2 rounded px-2 py-1 ${e.override ? "bg-red-950" : "bg-slate-900"}`}>
                  <summary className="cursor-pointer">
                    <span className="mr-2 font-mono text-xs text-slate-500">{new Date(e.t).toLocaleTimeString()}</span>
                    {e.override ? <b className="text-red-400">OVERRIDE: {e.override} </b> : null}
                    {e.text}
                  </summary>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {e.thumb && <img alt="frame" className="mt-1 w-full rounded" src={`data:image/jpeg;base64,${e.thumb}`} />}
                </details>
              )))}
            {tab === "imagination" && <p className="text-slate-500">Imagination arrives in P5/P6.</p>}
            {tab === "episodes" && <p className="text-slate-500">Episode history arrives in P10.</p>}
          </div>
        </aside>
      </main>
    </div>
  );
}
