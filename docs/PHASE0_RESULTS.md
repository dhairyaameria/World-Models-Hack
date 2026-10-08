# Phase 0 results (2026-10-08)

Raw tables: [P0A_er2_raw.md](P0A_er2_raw.md), [P0C_audio_trap_raw.md](P0C_audio_trap_raw.md). Reproduce with the commands in the README.

## P0-A: Gemini Robotics ER 2 on the 3 reference scenes

| Scene | Standard endpoint | Decision |
|---|---|---|
| Earthquake office | 3.2 s | Forward, toward the visible exit sign ✅ (but 0 hazards marked despite debris and wires ⚠️) |
| Flooded street | 3.3 s | Strafe left, away from sparking wires ✅ |
| Warehouse fire | 3.2 s | Turn left toward the exit door, away from the fire ✅ |

- **Use the standard endpoint** (`gemini-robotics-er-2-preview`) with an enforced JSON schema. The streaming endpoint is about 0.5 s faster, but with the frame sent as realtime video it misread scenes: it walked forward into the warehouse fire and called the street a corridor. It also returns its text in `output_transcription`, not `text`.
- **Latency is 2–3 s per decision with no audio.** The autopilot must decide every N frames and keep the previous move running in between (P3/P15).
- **Hazard recall is low on cluttered scenes.** Fix with example frames in the prompt and more emphasis on hazards (P3), then measure with the test set (P4.5).
- Gemini's schema format rejects integer enums (`Literal[1,2,3]`), so use `int` and clamp the value after parsing.

## P0-C: does hearing change the decision?

Same calm-corridor frame. Without audio, the agent moves **forward**. With audio, it got **7/7 right**:

| Sound (simulated direction) | Decision |
|---|---|
| Muffled "help" at −120° | Turn left toward the caller ✅ |
| "Don't come this way, the floor collapsed!" ahead | Don't advance; look for a side route ✅ |
| TV news voice at −60° | Flagged as a decoy and kept searching ✅ |
| Crying child at +100° | Turn right toward the child ✅ |
| Gas hiss ahead | Don't advance ✅ |
| Creaking overhead | Stop and look for another path ✅ |
| Muffled SOS knocking at +140° | Turn toward it ✅ |

- **Hearing works and is our clearest difference from a normal agent.** Lead the demo with it.
- **Audio raises latency to 5–7 s.** Only send audio when a sound is detected (P16). The fixed safety rules for gas, creaking and warnings must react instantly, without a model call.

## P0-C: does imagination change the choice at a trap?

The trap was smoke under the left door, with a clear stairwell on the right. **5/5 correct with or without imagined futures**: the smoke is visible, so ER 2 avoids it from the current frame alone. For imagination to make a difference, the traps need subtler cues (P9), for example a closed door with nothing visible and danger only behind it. Until a subtler trap shows a difference, don't lead the pitch with imagination.

## P0-B: Reactor (Lingbot-World-2)

- Status went connecting → waiting → **ready in about 3.6 s**, with the **first frame at about 9.6 s** (1664×960). Frame capture from the `<video>` works (no CORS or taint problems), moves sent from code steer the world, and Stop ends billing.
- **Token gotcha:** a session can only be operated by the token that created it. The JWT resolver must reuse one cached token, not mint a new one per request. Fixed in `frontend/lib/world.ts`.
- **Scene drift:** over about 20 s, the earthquake corridor drifted toward a clean, blue-lit hallway. Next step: re-assert the scenario with a prompt change every so often, or trigger a memory reset (`triggerKvCacheReset`).

## Quotas

The free tier allows **3 requests/min for TTS**. `with_quota_retry` waits out the limit for asset generation. Six ER 2 calls in a row went through, but the 2-fps agent loop and data collection (P12) will need a **paid tier** on the AI Studio project.
