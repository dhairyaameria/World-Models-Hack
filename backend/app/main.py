"""RescueSim backend: FastAPI app implementing shared/contract.md."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .autopilot import live_decision  # noqa: E402
from .mock_agent import mock_decision  # noqa: E402
from .models import (  # noqa: E402
    AudioTrigger,
    ClientEnvelope,
    DirectorEvent,
    DirectorTrigger,
    EndEpisode,
    EpisodeStarted,
    EpisodeSummary,
    ErrorMessage,
    Frame,
    ImagineResults,
    NetworkSim,
    SetAgent,
    StartEpisode,
)
from .scenarios import get_scenario, get_scenarios  # noqa: E402
from .state import Episode, EpisodeStore  # noqa: E402

AGENT_MODE = os.getenv("AGENT_MODE", "mock")
DECISION_MIN_INTERVAL_S = float(os.getenv("DECISION_MIN_INTERVAL_MS", "500")) / 1000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("rescuesim")

app = FastAPI(title="RescueSim backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

store = EpisodeStore()


class Connection:
    """One browser WebSocket. Processes only the latest frame per episode (never queues)."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.send_lock = asyncio.Lock()
        self.pending: dict[str, Frame] = {}
        self.workers: dict[str, asyncio.Task] = {}
        self.offline = False

    async def send(self, msg: BaseModel) -> None:
        async with self.send_lock:
            await self.ws.send_text(msg.model_dump_json())

    def submit_frame(self, frame: Frame) -> None:
        if frame.episode_id in self.pending:
            log.debug("dropping stale frame for %s", frame.episode_id)
        self.pending[frame.episode_id] = frame
        task = self.workers.get(frame.episode_id)
        if task is None or task.done():
            self.workers[frame.episode_id] = asyncio.create_task(self._work(frame.episode_id))

    async def _work(self, episode_id: str) -> None:
        last = 0.0
        while episode_id in self.pending:
            wait = DECISION_MIN_INTERVAL_S - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
            frame = self.pending.pop(episode_id, None)
            ep = store.get(episode_id)
            if frame is None or ep is None or ep.outcome is not None:
                return
            last = time.monotonic()
            try:
                decision = await decide(ep, frame, offline=self.offline)
            except Exception:  # never crash the loop; the HUD shows "re-assessing"
                log.exception("decision failed for %s", episode_id)
                continue
            ep.record("decision", decision=decision.model_dump(exclude={"type"}))
            log.info("decision ep=%s move=%s look=%s latency=%.0fms", ep.id,
                     decision.action.move, decision.action.look, decision.latency_ms)
            await self.send(decision)

    def cancel(self) -> None:
        for t in self.workers.values():
            t.cancel()


async def decide(ep: Episode, frame: Frame, offline: bool):
    if AGENT_MODE == "mock":
        await asyncio.sleep(0.05)
        return mock_decision(ep)
    if AGENT_MODE == "live":
        return await live_decision(ep, frame.jpeg_b64)
    raise NotImplementedError(f"AGENT_MODE={AGENT_MODE}")


connections: set[Connection] = set()


async def broadcast_to_episode(episode_id: str, msg: BaseModel) -> None:
    # Single-operator app: send to every connection; clients filter by episode_id.
    for conn in list(connections):
        try:
            await conn.send(msg)
        except Exception:
            log.warning("broadcast failed; dropping connection")
            connections.discard(conn)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn = Connection(ws)
    connections.add(conn)
    log.info("ws connected (%d open)", len(connections))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = ClientEnvelope.model_validate_json(f'{{"msg": {raw}}}').msg
            except ValidationError as e:
                await conn.send(ErrorMessage(message=f"invalid message: {e.errors()[:3]}"))
                continue
            try:
                await handle(conn, msg)
            except HTTPException as e:
                await conn.send(ErrorMessage(message=str(e.detail)))
    except WebSocketDisconnect:
        pass
    finally:
        conn.cancel()
        connections.discard(conn)
        log.info("ws disconnected (%d open)", len(connections))


async def handle(conn: Connection, msg: Any) -> None:
    if isinstance(msg, StartEpisode):
        scenario = get_scenario(msg.scenario_id)
        if scenario is None:
            await conn.send(ErrorMessage(message=f"unknown scenario {msg.scenario_id}"))
            return
        ep = store.create(scenario=scenario, mode=msg.mode, agent=msg.agent,
                          imagination=msg.imagination, hearing=msg.hearing, pair_id=msg.pair_id)
        ep.record("start", mode=msg.mode, agent=msg.agent)
        log.info("episode %s started scenario=%s mode=%s agent=%s", ep.id, scenario.id,
                 msg.mode, msg.agent)
        await conn.send(EpisodeStarted(episode_id=ep.id, scenario=scenario))
    elif isinstance(msg, Frame):
        if store.get(msg.episode_id) is None:
            await conn.send(ErrorMessage(message=f"unknown episode {msg.episode_id}"))
            return
        conn.submit_frame(msg)
    elif isinstance(msg, SetAgent):
        ep = _require(msg.episode_id)
        ep.agent = msg.agent
        ep.record("set_agent", agent=msg.agent)
    elif isinstance(msg, NetworkSim):
        conn.offline = msg.offline
        log.info("network_sim offline=%s", msg.offline)
    elif isinstance(msg, ImagineResults):
        ep = _require(msg.episode_id)
        ep.record("imagine_results", request_id=msg.request_id,
                  options=[o.label for o in msg.options])
    elif isinstance(msg, EndEpisode):
        ep = _require(msg.episode_id)
        ep.outcome = msg.outcome
        ep.record("end", outcome=msg.outcome)
        path = ep.save()
        log.info("episode %s ended outcome=%s saved=%s", ep.id, msg.outcome, path.name)
        await conn.send(EpisodeSummary(episode_id=ep.id, score=0, outcome=msg.outcome))


def _require(episode_id: str) -> Episode:
    ep = store.get(episode_id)
    if ep is None:
        raise HTTPException(404, f"unknown episode {episode_id}")
    return ep


# ---------- HTTP ----------

@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "agent_mode": AGENT_MODE, "gemini_key": bool(os.getenv("GEMINI_API_KEY"))}


@app.get("/scenarios")
def scenarios():
    return get_scenarios()


@app.get("/episodes")
def episodes():
    return store.list()


@app.post("/director/trigger")
async def director_trigger(body: DirectorTrigger) -> dict[str, Any]:
    event = body.event or ("A sudden aftershock shakes the corridor: ceiling panels crash down ahead and a "
                           "thick cloud of grey dust rolls toward the camera")
    for eid in body.episode_ids:
        ep = _require(eid)
        ep.record("director", event=event)
        ep.events.append((time.time(), event))
        await broadcast_to_episode(eid, DirectorEvent(
            episode_id=eid, kind="director",
            world_prompt=f"{ep.scenario.world_prompt} {event}", clause=event,
            caption=event.split(":")[0].upper()))
    return {"ok": True, "event": event}


@app.post("/audio/trigger")
async def audio_trigger(body: AudioTrigger) -> dict[str, Any]:
    raise HTTPException(501, "audio engine not implemented yet (P16)")


@app.post("/live/token")
async def live_token() -> dict[str, Any]:
    raise HTTPException(501, "Live guide not implemented yet (P7)")


@app.get("/models")
def models_list() -> list[dict[str, Any]]:
    return []


@app.get("/experiments/results")
def experiments_results() -> Optional[dict[str, Any]]:
    return None
