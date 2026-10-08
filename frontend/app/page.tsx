"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioRadar } from "@/components/AudioRadar";
import { HudOverlay } from "@/components/HudOverlay";
import { ImaginationOverlay, type ImaginationView } from "@/components/ImaginationOverlay";
import { runImagination } from "@/lib/imagine";
import { AudioScenePlayer, type AudioSourceState } from "@/lib/audioScene";
import { BackendClient } from "@/lib/backend";
import { BACKEND_HTTP, type Decision, type Heard, type Mode, type Pose, type Scenario, type ServerMessage } from "@/lib/contract";
import { frameBlob, ReactorWorld, StaticWorld, type World } from "@/lib/world";

const CALLOUT_URL = "/static/audio/voices/robot_callout.wav";
const VERDICT_HOLD_MS = 4500;

const FRAME_INTERVAL_MS = Number(process.env.NEXT_PUBLIC_FRAME_INTERVAL_MS ?? 500);
type WorldKind = "static" | "reactor";
type LogEntry = { id: number; t: number; text: string; override?: string | null; thumb?: string | null; repeat?: number };
type Banner = { text: string; tone: "danger" | "found" };

// Operator palette: inject a sound relative to the robot's current pose (POST /audio/trigger).
const INJECT_PRESETS = [
  { label: "🗣 Cry for help · behind-left", bearing: -130, distance: 7, source: {
    kind: "voice", clip_url: "/static/audio/voices/help_im_stuck_weak.wav", muffled: true, urgency: 3,
    reveal: { radius_m: 3, world_prompt: "A dust-covered person lies trapped under a collapsed desk, waving one arm toward the camera.", caption: "Survivor trapped under debris" } } },
  { label: "🧒 Child crying · right", bearing: 100, distance: 9, source: {
    kind: "voice", clip_url: "/static/audio/voices/is_anyone_there_child.wav", urgency: 3,
    reveal: { radius_m: 3, world_prompt: "A frightened child crouches beside an overturned cabinet, looking at the camera.", caption: "Child found" } } },
  { label: "💨 Gas hiss · ahead", bearing: 8, distance: 4, source: {
    kind: "gas_hiss", clip_url: "/static/audio/fx/gas_hiss.wav", is_hazard: true, severity: 3 } },
  { label: "🏚 Creaking · overhead", bearing: 0, distance: 3, source: {
    kind: "creak", clip_url: "/static/audio/fx/creak.wav", is_hazard: true, severity: 3, stop_s: 25 } },
  { label: "⚠️ \"Don't come this way!\"", bearing: 5, distance: 10, source: {
    kind: "voice", clip_url: "/static/audio/voices/dont_come_this_way.wav", is_hazard: true, loop: false } },
  { label: "🔨 SOS tapping · behind-right", bearing: 140, distance: 7, source: {
    kind: "tapping", clip_url: "/static/audio/fx/sos_knock.wav", muffled: true, urgency: 3,
    reveal: { radius_m: 3, world_prompt: "A worker pinned behind fallen boxes knocks on a metal shelf with a wrench.", caption: "Survivor found by tapping" } } },
  { label: "📺 TV voice (decoy) · left", bearing: -70, distance: 6, source: {
    kind: "tv_radio", clip_url: "/static/audio/voices/tv_news_decoy.wav", is_decoy: true } },
] as const;

export default function MissionControl() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const [worldKind, setWorldKind] = useState<WorldKind>(
    process.env.NEXT_PUBLIC_DEFAULT_WORLD === "reactor" ? "reactor" : "static",
  );
  const [mode, setMode] = useState<Mode>("autopilot");
  const [hearing, setHearing] = useState(true);
  const [imagination, setImagination] = useState(true);
  const [imagineView, setImagineView] = useState<ImaginationView | null>(null);
  const [imagineHistory, setImagineHistory] = useState<{ id: string; reason: string; chosen: string }[]>([]);

  const [connected, setConnected] = useState(false);
  const [worldStatus, setWorldStatus] = useState("idle");
  const [episodeId, setEpisodeId] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [receivedAt, setReceivedAt] = useState(0);
  const [trail, setTrail] = useState<Pose[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [truth, setTruth] = useState<AudioSourceState[]>([]);
  const [heard, setHeard] = useState<Heard[]>([]);
  const [showTruth, setShowTruth] = useState(false);
  const [hearingActive, setHearingActive] = useState(false);
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
  const player = useRef<AudioScenePlayer | null>(null);
  const injectId = useRef(0);
  const imagining = useRef(false);
  const scenarioRef = useRef<Scenario | null>(null);
  const worldKindRef = useRef<WorldKind>("static");

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
    setHeard(d.heard);
    setStats((s) => ({
      ...s,
      steps: s.steps + 1,
      survivors: s.survivors + d.survivors.length,
      hazardsAvoided: s.hazardsAvoided + (d.safety_override || (d.hazards.length && d.action.move !== "W") ? 1 : 0),
    }));
    const entry = { id: logId.current++, t: Date.now(), text: d.reason, override: d.safety_override, thumb: lastThumb.current };
    setLog((l) => (l[0] && l[0].text === entry.text && !entry.override
      ? [{ ...l[0], t: entry.t, thumb: entry.thumb, repeat: (l[0].repeat ?? 1) + 1 }, ...l.slice(1)]
      : [entry, ...l].slice(0, 200)));
  }, []);

  const imagine = useCallback(async (req: Extract<ServerMessage, { type: "imagine_request" }>) => {
    const main = world.current;
    const scenario = scenarioRef.current;
    if (!main || !scenario) return;
    imagining.current = true;
    const blob = frameBlob(main);
    await main.pause();
    setImagineView({ requestId: req.request_id, options: req.options, status: {}, tiles: {} });
    if (!blob) return;
    const options = await runImagination(worldKindRef.current, blob, scenario.world_prompt, req.options, {
      onTile: (id, el) => setImagineView((v) => (v ? { ...v, tiles: { ...v.tiles, [id]: el } } : v)),
      onStatus: (id, st) => setImagineView((v) => (v ? { ...v, status: { ...v.status, [id]: st } } : v)),
      onFrames: (id, fr) => setImagineView((v) => (v ? { ...v, frames: { ...v.frames, [id]: fr } } : v)),
    });
    backend.current?.send({ type: "imagine_results", episode_id: req.episode_id, request_id: req.request_id, options });
  }, []);

  useEffect(() => {
    const client = backend.current;
    if (!client) return;
    return client.subscribe((msg) => {
      if (msg.type === "decision") handleDecision(msg);
      else if (msg.type === "audio_state" && msg.episode_id === episodeRef.current) {
        player.current?.update(msg.sources);
        setTruth(msg.sources);
      } else if (msg.type === "director_event" && msg.episode_id === episodeRef.current) {
        void world.current?.addEvent(msg.clause ?? msg.world_prompt);
        setBanner({ text: msg.caption, tone: msg.kind === "reveal" ? "found" : "danger" });
        if (msg.kind === "reveal") setStats((st) => ({ ...st, survivors: st.survivors + 1 }));
        setTimeout(() => setBanner(null), msg.kind === "reveal" ? 5000 : 4000);
      } else if (msg.type === "imagine_request" && msg.episode_id === episodeRef.current) {
        void imagine(msg);
      } else if (msg.type === "imagine_verdict" && msg.episode_id === episodeRef.current) {
        setImagineView((v) => (v && v.requestId === msg.request_id ? { ...v, verdict: msg } : v));
        const chosen = msg.chosen_id;
        setImagineHistory((h) => [{ id: msg.request_id, reason: msg.reason, chosen }, ...h]);
        setTimeout(async () => {
          setImagineView(null);
          await world.current?.resume();
          imagining.current = false;
        }, VERDICT_HOLD_MS);
      } else if (msg.type === "error") setError(msg.message);
    });
  }, [handleDecision, imagine, connected]);


  // Frame loop: capture -> backend while an episode runs.
  useEffect(() => {
    if (!episodeId) return;
    const id = setInterval(() => {
      if (imagining.current) return; // main world is paused while the robot imagines
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
    player.current ??= new AudioScenePlayer();
    player.current.unlock(); // inside the click handler, so the browser allows audio

    const w: World = worldKind === "reactor" ? new ReactorWorld() : new StaticWorld();
    w.onStatus = setWorldStatus;
    world.current = w;
    w.video.className = "h-full w-full object-cover";
    videoHost.current?.replaceChildren(w.video);
    scenarioRef.current = scenario;
    worldKindRef.current = worldKind;
    imagining.current = false;
    setImagineView(null);
    setImagineHistory([]);
    try {
      await w.start(`${BACKEND_HTTP}${scenario.reference_image_url}`, scenario.world_prompt);
      await w.ready(40000); // start the episode clock when the world is actually visible
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
      client.send({ type: "start_episode", scenario_id: scenario.id, mode, agent: "cloud", imagination, hearing });
    });
    episodeRef.current = started;
    startedAt.current = performance.now();
    setStats({ steps: 0, survivors: 0, hazardsAvoided: 0, elapsedS: 0 });
    setTrail([{ x: 0, y: 0, heading_deg: 0 }]);
    setLog([]);
    setDecision(null);
    setHeard([]);
    setTruth([]);
    setHearingActive(hearing);
    setEpisodeId(started);
    if (hearing) void player.current.playOnce(CALLOUT_URL, 0.8); // "If you can hear me, call out!"
  }

  async function stop(outcome: "timeout" | "escaped" | "failed" = "timeout") {
    if (episodeId) backend.current?.send({ type: "end_episode", episode_id: episodeId, outcome });
    episodeRef.current = null;
    setEpisodeId(null);
    player.current?.stopAll();
    await world.current?.stop();
    setWorldStatus("idle");
  }

  async function inject(preset: (typeof INJECT_PRESETS)[number]) {
    if (!episodeId) return;
    await fetch(`${BACKEND_HTTP}/audio/trigger`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        episode_ids: [episodeId],
        bearing_deg: preset.bearing,
        distance_m: preset.distance,
        source: { id: `inj_${preset.source.kind}_${injectId.current++}`, position: [0, 0], ...preset.source },
      }),
    });
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
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={imagination} disabled={running} onChange={(e) => setImagination(e.target.checked)} />
          Imagination
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
          {running && <AudioRadar heard={heard} truth={truth} showTruth={showTruth} hearingOn={hearingActive} />}
          {imagineView && <ImaginationOverlay view={imagineView} />}
          {banner && (
            <div className={`absolute left-0 right-0 top-1/3 py-3 text-center text-2xl font-bold tracking-wide ${
              banner.tone === "found" ? "bg-green-700/90" : "bg-red-700/90"}`}>
              {banner.tone === "found" ? "🗣 " : "⚠ "}{banner.text}
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
          {running && (
            <div className="border-b border-slate-800 p-2">
              <div className="mb-1 flex items-center justify-between text-xs uppercase tracking-wide text-slate-400">
                <span>Inject sound</span>
                <label className="flex items-center gap-1 normal-case">
                  <input type="checkbox" checked={showTruth} onChange={(e) => setShowTruth(e.target.checked)} />
                  show true positions
                </label>
              </div>
              <div className="flex flex-wrap gap-1">
                {INJECT_PRESETS.map((p) => (
                  <button key={p.label} onClick={() => inject(p)}
                    className="rounded bg-slate-800 px-2 py-1 text-xs hover:bg-slate-700">{p.label}</button>
                ))}
              </div>
            </div>
          )}
          <div className="flex-1 overflow-y-auto p-3 text-sm">
            {tab === "log" && (log.length === 0
              ? <p className="text-slate-500">Decisions appear here.</p>
              : log.map((e) => (
                <details key={e.id} className={`mb-2 rounded px-2 py-1 ${e.override ? "bg-red-950" : "bg-slate-900"}`}>
                  <summary className="cursor-pointer">
                    <span className="mr-2 font-mono text-xs text-slate-500">{new Date(e.t).toLocaleTimeString()}</span>
                    {e.override ? <b className="text-red-400">OVERRIDE: {e.override} </b> : null}
                    {e.text}
                    {e.repeat && e.repeat > 1 ? <span className="ml-1 text-xs text-slate-500">×{e.repeat}</span> : null}
                  </summary>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {e.thumb && <img alt="frame" className="mt-1 w-full rounded" src={`data:image/jpeg;base64,${e.thumb}`} />}
                </details>
              )))}
            {tab === "imagination" && (imagineHistory.length === 0
              ? <p className="text-slate-500">When the robot locates a survivor, it imagines each route in a forked world before moving.</p>
              : imagineHistory.map((h) => (
                <div key={h.id} className="mb-2 rounded bg-slate-900 px-2 py-1">
                  <div className="text-xs text-sky-300">chose: {h.chosen}</div>
                  <div>{h.reason}</div>
                </div>
              )))}
            {tab === "episodes" && <p className="text-slate-500">Episode history arrives in P10.</p>}
          </div>
        </aside>
      </main>
    </div>
  );
}
