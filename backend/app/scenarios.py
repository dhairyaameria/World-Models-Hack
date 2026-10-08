"""Preset scenarios. These are the reliable ones for the demo; generated ones come later (P9)."""

from __future__ import annotations

from .models import AudioSource, Reveal, Scenario

PRESETS: list[Scenario] = [
    Scenario(
        id="earthquake_office",
        title="Earthquake: Office Floor",
        description="Third floor of an office after a strong earthquake. Dust, fallen ceiling "
        "tiles, overturned desks. A green exit sign glows at the far end of the corridor.",
        world_prompt=(
            "first-person view walking through a dim office corridor after an earthquake, "
            "fallen ceiling tiles and overturned desks, dust in the air, flickering lights, "
            "a green emergency exit sign far down the corridor, realistic, handheld camera"
        ),
        reference_image_url="/static/scenarios/earthquake_office.jpg",
        audio_sources=[
            AudioSource(
                id="office_caller",
                kind="voice",
                position=(-6.0, 4.0),
                clip_url="/static/audio/voices/help_im_stuck_weak.wav",
                muffled=True,
                transcript="Help! I'm stuck under here!",
                urgency=3,
                reveal=Reveal(
                    world_prompt="a person trapped under a collapsed desk, waving one arm, "
                    "covered in dust, looking at the camera",
                    caption="Survivor trapped under a desk",
                ),
            ),
            AudioSource(
                id="office_creak",
                kind="creak",
                position=(0.5, 9.0),
                clip_url="/static/audio/fx/creak.wav",
                is_hazard=True,
                severity=3,
                start_s=20,
            ),
        ],
    ),
    Scenario(
        id="flooded_street",
        title="Flood: Downtown Street",
        description="Street-level flooding after a storm. Murky water, floating debris, "
        "downed power lines. A raised pedestrian bridge leads to safety.",
        world_prompt=(
            "first-person view on a flooded city street after a storm, knee-deep murky brown "
            "water, floating debris, a downed power line sparking near a lamp post, abandoned "
            "cars, a raised pedestrian bridge with a green exit sign in the distance, overcast"
        ),
        reference_image_url="/static/scenarios/flooded_street.jpg",
        audio_sources=[
            AudioSource(
                id="street_water",
                kind="water",
                position=(4.0, 6.0),
                clip_url="/static/audio/fx/rushing_water.wav",
                is_hazard=True,
                severity=2,
            ),
            AudioSource(
                id="street_caller",
                kind="voice",
                position=(-8.0, 10.0),
                clip_url="/static/audio/voices/over_here_shout.wav",
                transcript="Over here! On the car roof!",
                urgency=2,
                reveal=Reveal(
                    world_prompt="a person standing on the roof of a half-submerged car, "
                    "waving both arms",
                    caption="Survivor on a car roof",
                ),
            ),
        ],
    ),
    Scenario(
        id="warehouse_fire",
        title="Fire: Warehouse",
        description="Smoke-filled warehouse with a fire spreading in the back aisles. "
        "Tall shelving, a forklift, and an exit door on the left wall.",
        world_prompt=(
            "first-person view inside a large warehouse filled with grey smoke, tall metal "
            "shelving aisles, orange fire glow at the back, a forklift, a green exit sign "
            "above a door on the left wall, realistic"
        ),
        reference_image_url="/static/scenarios/warehouse_fire.jpg",
        audio_sources=[
            AudioSource(
                id="warehouse_fire_crackle",
                kind="fire",
                position=(2.0, 14.0),
                clip_url="/static/audio/fx/fire_crackle.wav",
                is_hazard=True,
                severity=3,
            ),
            AudioSource(
                id="warehouse_gas",
                kind="gas_hiss",
                position=(3.0, 5.0),
                clip_url="/static/audio/fx/gas_hiss.wav",
                is_hazard=True,
                severity=3,
                start_s=15,
            ),
            AudioSource(
                id="warehouse_tapping",
                kind="tapping",
                position=(-5.0, 8.0),
                clip_url="/static/audio/fx/sos_knock.wav",
                muffled=True,
                urgency=3,
                reveal=Reveal(
                    world_prompt="a worker pinned behind fallen boxes, knocking on a metal "
                    "shelf with a wrench",
                    caption="Survivor found by tapping",
                ),
            ),
        ],
    ),
]


def get_scenarios() -> list[Scenario]:
    return list(PRESETS)


def get_scenario(scenario_id: str) -> Scenario | None:
    return next((s for s in PRESETS if s.id == scenario_id), None)
