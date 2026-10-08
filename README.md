# RescueSim

An autonomous disaster-rescue agent that sees and hears, running inside a real-time world model (Reactor, Lingbot-World-2) with Gemini Robotics ER 2 as its brain. Plan and step-by-step prompts: [BUILD_PROMPTS.md](BUILD_PROMPTS.md). Message contract: [shared/contract.md](shared/contract.md).

## Status

| Phase | State |
|---|---|
| P0 tests | Scripts ready (`backend/spikes/`); need API keys to run |
| P1 backend skeleton + mock agent | Done (tests pass) |
| P2 frontend skeleton + Reactor client | Done; full loop verified in the browser with the free Static world + mock agent. Reactor path written against SDK types, not yet run with a key |
| P3 onwards | Not started |

## Setup

```bash
# backend
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # add GEMINI_API_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000

# frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local    # add REACTOR_API_KEY
npm run dev                   # http://localhost:3000
```

The `.env` files are git-ignored. Never commit keys.

Run the tests with `cd backend && .venv/bin/python -m pytest -q`.

## Running without keys

- `AGENT_MODE=mock` (the default) returns random but plausible decisions.
- **World: Static** in the UI pans over the scenario's reference image instead of streaming Reactor. It's free.

## With keys: Phase 0

```bash
cd backend
.venv/bin/python -m scripts.list_models robotics   # confirm ER 2 model IDs; also try: tts, image, flash
.venv/bin/python -m scripts.make_assets            # reference images + TTS voices (+ fx, already committed)
.venv/bin/python -m spikes.er2_spike               # P0-A -> spikes/out_er2/
.venv/bin/python -m spikes.audio_trap_spike        # P0-C -> spikes/out_p0c/RESULTS_P0C.md
```

For P0-B, set **World: Reactor** in the UI and press Start. Billing runs at about $0.42/min while a session is live, so press Stop when you're done.

Model IDs are set in `backend/.env` through `ER2_MODEL`, `ER2_STREAMING_MODEL`, `GEMINI_FLASH_MODEL`, `GEMINI_IMAGE_MODEL` and `GEMINI_TTS_MODEL`. Defaults are in `backend/app/genai_client.py`.

## Reactor facts (from SDK types + docs, Oct 2026)

- Packages: `@reactor-models/lingbot-world-2` (typed model client) on top of `@reactor-team/js-sdk`. Video is delivered over WebRTC.
- Starting a session needs both an image and a prompt: `uploadFile` → `setImage` → `setPrompt` → `start`. A new image only takes effect after `reset`; prompts can be changed while the stream runs.
- Controls are **persistent states**, not timed moves: `setMoveLongitudinal` (forward/back/idle), `setMoveLateral`, `setLookHorizontal`, `setLookVertical`. `ReactorWorld.sendAction` switches each back to idle after `duration_ms`. Rotation speed is set in degrees per generated frame, 0–30.
- Limits: 5 concurrent sessions per account and 10 new sessions per minute. Lingbot-World-2 costs $0.007/s.
- Auth: the server mints a scoped JWT at `POST https://api.reactor.inc/tokens` (`frontend/app/api/reactor-token/route.ts`), so the `rk_` key never reaches the browser.

## Sounds

Gemini TTS generates the voices (`scripts/make_assets.py`). The non-voice effects (gas hiss, creak, SOS knocking, water, fire, alarm) are generated in code (`app/audio_synth.py`), so there's nothing to license.
