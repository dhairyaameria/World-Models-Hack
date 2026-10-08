import json
import os
import tempfile

os.environ["AGENT_MODE"] = "mock"
os.environ["DECISION_MIN_INTERVAL_MS"] = "0"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="rescuesim-test-")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models import Action, Pose  # noqa: E402
from app.state import integrate  # noqa: E402

client = TestClient(app)

TINY_JPEG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"


def test_health_and_scenarios():
    assert client.get("/health").json()["ok"] is True
    scenarios = client.get("/scenarios").json()
    assert {s["id"] for s in scenarios} >= {"earthquake_office", "flooded_street", "warehouse_fire"}


def test_episode_frame_decision_end():
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "start_episode", "scenario_id": "earthquake_office",
                                 "mode": "autopilot", "agent": "cloud",
                                 "imagination": False, "hearing": False}))
        started = json.loads(ws.receive_text())
        assert started["type"] == "episode_started"
        eid = started["episode_id"]

        ws.send_text(json.dumps({"type": "frame", "episode_id": eid, "ts": 0,
                                 "jpeg_b64": TINY_JPEG_B64}))
        decision = json.loads(ws.receive_text())
        assert decision["type"] == "decision"
        assert decision["action"]["move"] in {"W", "A", "S", "D", "none"}
        assert set(decision["pose"]) == {"x", "y", "heading_deg"}

        ws.send_text(json.dumps({"type": "end_episode", "episode_id": eid, "outcome": "timeout"}))
        summary = json.loads(ws.receive_text())
        assert summary["type"] == "episode_summary"


def test_invalid_message_returns_error():
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "nope"}))
        assert json.loads(ws.receive_text())["type"] == "error"
        ws.send_text(json.dumps({"type": "frame", "episode_id": "missing", "ts": 0,
                                 "jpeg_b64": ""}))
        assert json.loads(ws.receive_text())["type"] == "error"


def test_dead_reckoning():
    p = integrate(Pose(), Action(move="W", duration_ms=1000))
    assert abs(p.y - 1.0) < 1e-6 and abs(p.x) < 1e-6
    p = integrate(p, Action(look="right", duration_ms=1500))  # 90 degrees right
    assert abs(p.heading_deg - 90) < 1e-6
    p = integrate(p, Action(move="W", duration_ms=1000))
    assert abs(p.x - 1.0) < 1e-6 and abs(p.y - 1.0) < 1e-6
