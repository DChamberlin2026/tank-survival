"""
Never-ending single-player Pygame “tank survival scavenging” prototype
---------------------------------------------------------------------
How to run:
  pip install pygame
  python tank_game.py

Assets:
Put your placeholder PNGs in a folder named: assets/

Expected (optional) filenames (if missing, the game uses colored placeholders):
  # Internal views (4)
  assets/internal_driver.png
  assets/internal_engine.png
  assets/internal_left.png
  assets/internal_right.png

  # Outside views (3)
  assets/outside_driver.png
  assets/outside_left.png
  assets/outside_right.png

You can later replace these with your actual Mk V tank images / no-man’s-land images.

Controls:
  - Click UI buttons.
  - In outside LEFT/RIGHT views during a LEVEL: click zombies to shoot them (costs 1 shell).
Gameplay summary:
  - While DRIVING: fuel burns down; random breakdown occurs 30s–180s after last level ended; or fuel hits 0.
  - LEVEL (stopped): you can shoot zombies (left/right outside), then (optionally) send scavenger(s).
  - Each level guarantees at least 1 PART exists somewhere in the “level loot pool”.
  - Fix Engine requires 1 PART. After fixing, go to Driver view and Start to resume driving (ends the level).
  - Stop while driving immediately starts a new level.
"""

import os
import sys
import random
import math
import pygame
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

# -----------------------------
# USER-TUNABLE VARIABLES (TOP)
# -----------------------------
SCREEN_W, SCREEN_H = 1100, 650
FPS = 60

ASSET_DIR = "assets"

# Starting resources
STARTING_FUEL = 200
STARTING_SHELLS = 6
STARTING_GUNS = 4
STARTING_CREW = 4
STARTING_PARTS = 0

# Fuel behavior
FUEL_CONSUMED_PER_SECOND = 1.0  # while driving

# Breakdown timing
BREAKDOWN_MIN_SECONDS = 30
BREAKDOWN_MAX_SECONDS = 180

# Level population tuning (items & zombies)
ZOMBIES_MIN = 1
ZOMBIES_MAX = 8

FUELCANS_MIN = 1
FUELCANS_MAX = 5

SHELLS_MIN = 0
SHELLS_MAX = 4

PARTS_MIN = 1   # guarantee at least 1
PARTS_MAX = 2

# Fuelcan yield (when scavenged)
FUELCAN_YIELD_MIN = 10
FUELCAN_YIELD_MAX = 100

# Scavenging base chances & loot fractions
SCAVENGE_MODES = {
    "QUICK":    {"base_return": 0.75, "loot_frac": 1/3},
    "MODERATE": {"base_return": 0.50, "loot_frac": 0.50},
    "GREEDY":   {"base_return": 0.33, "loot_frac": 1.00},
}

# Zombie pressure: how much each zombie modifies return chance (clamped later)
ZOMBIE_PENALTY_PER = 0.04     # each zombie reduces chance
GUN_BONUS = 0.15              # if you give scavenger a gun, increase chance


# -----------------------------
# BASIC UI HELPERS
# -----------------------------
pygame.init()
pygame.font.init()

FONT = pygame.font.SysFont("consolas", 20)
FONT_BIG = pygame.font.SysFont("consolas", 28, bold=True)

WHITE = (240, 240, 240)
BLACK = (0, 0, 0)
DARK = (20, 20, 20)
MID = (55, 55, 55)
LIGHT = (90, 90, 90)
RED = (200, 70, 70)
GREEN = (70, 200, 120)
YELLOW = (220, 200, 80)


def clamp(x, a, b):
    return max(a, min(b, x))


def draw_text(surface, text, pos, color=WHITE, font=FONT):
    img = font.render(text, True, color)
    surface.blit(img, pos)


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    action: str
    enabled: bool = True

    def draw(self, surface):
        base = LIGHT if self.enabled else MID
        pygame.draw.rect(surface, base, self.rect, border_radius=10)
        pygame.draw.rect(surface, DARK, self.rect, 2, border_radius=10)
        # center label
        lbl = FONT.render(self.label, True, BLACK if self.enabled else (30, 30, 30))
        r = lbl.get_rect(center=self.rect.center)
        surface.blit(lbl, r)

    def hit(self, mouse_pos):
        return self.enabled and self.rect.collidepoint(mouse_pos)


# -----------------------------
# GAME STATE
# -----------------------------
V_DRIVER = "DRIVER"
V_ENGINE = "ENGINE"
V_LEFT = "LEFT_GUNNER"
V_RIGHT = "RIGHT_GUNNER"

V_OUT_DRIVER = "OUT_DRIVER"
V_OUT_LEFT = "OUT_LEFT"
V_OUT_RIGHT = "OUT_RIGHT"

INTERNAL_VIEWS = [V_DRIVER, V_ENGINE, V_LEFT, V_RIGHT]
OUTSIDE_VIEWS = [V_OUT_DRIVER, V_OUT_LEFT, V_OUT_RIGHT]


@dataclass
class LevelPool:
    fuelcans: int
    shells: int
    parts: int
    zombies: int

    def total_items(self) -> int:
        return self.fuelcans + self.shells + self.parts


@dataclass
class GameState:
    fuel: int = STARTING_FUEL
    shells: int = STARTING_SHELLS
    guns: int = STARTING_GUNS
    crew: int = STARTING_CREW
    parts: int = STARTING_PARTS

    moving: bool = True
    engine_broken: bool = False

    # time until next breakdown (when moving)
    breakdown_at_ms: int = 0

    # current view
    view: str = V_DRIVER

    # current “level”
    in_level: bool = False
    level_pool: Optional[LevelPool] = None

    # popup / modal
    popup_text: Optional[str] = None

    # scavenging modal
    scavenging_mode: Optional[str] = None  # "QUICK" / "MODERATE" / "GREEDY"
    scavenging_give_gun: bool = False
    scavenging_confirm: bool = False

    # transition
    transitioning: bool = False
    trans_from: Optional[str] = None
    trans_to: Optional[str] = None
    trans_t: float = 0.0  # 0..1 for fade


# -----------------------------
# ASSET LOADING (with fallbacks)
# -----------------------------
def load_image(path: str, size: Tuple[int, int]) -> pygame.Surface:
    full = os.path.join(ASSET_DIR, path)
    if os.path.exists(full):
        try:
            img = pygame.image.load(full).convert_alpha()
            return pygame.transform.smoothscale(img, size)
        except Exception:
            pass
    # fallback placeholder
    surf = pygame.Surface(size)
    surf.fill((35, 35, 35))
    pygame.draw.rect(surf, (120, 120, 120), surf.get_rect(), 4)
    draw_text(surf, f"MISSING: {path}", (20, 20), YELLOW, FONT_BIG)
    return surf


def make_placeholder_sprite(label: str, w: int, h: int, color=(120, 120, 120)) -> pygame.Surface:
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(s, color, (0, 0, w, h), border_radius=8)
    pygame.draw.rect(s, DARK, (0, 0, w, h), 2, border_radius=8)
    txt = FONT.render(label, True, BLACK)
    s.blit(txt, txt.get_rect(center=(w//2, h//2)))
    return s


# -----------------------------
# OUTSIDE SPRITES (ZOMBIES ETC)
# -----------------------------
@dataclass
class SpriteObj:
    kind: str  # "ZOMBIE" (shootable) or "ITEM" (cosmetic for now)
    rect: pygame.Rect


def gen_outside_sprites_for_view(view: str, pool: LevelPool) -> List[SpriteObj]:
    """
    We visually place zombies (shootable) and “item markers” (not directly pick-up, just to show what exists).
    Actual resource acquisition is via scavenging, per your description.
    """
    sprites: List[SpriteObj] = []

    # Scatter zombies; show them in all outside views, but only shootable in OUT_LEFT/OUT_RIGHT per your spec.
    z = pool.zombies
    for _ in range(z):
        x = random.randint(80, SCREEN_W - 180)
        y = random.randint(120, SCREEN_H - 140)
        sprites.append(SpriteObj("ZOMBIE", pygame.Rect(x, y, 80, 80)))

    # Scatter item markers (fuel/parts/shells). Cosmetic indicators only.
    # Place fewer markers to avoid clutter.
    markers = []
    markers += ["FUEL"] * min(pool.fuelcans, 4)
    markers += ["PART"] * min(pool.parts, 2)
    markers += ["SHELL"] * min(pool.shells, 3)
    random.shuffle(markers)

    for m in markers:
        x = random.randint(60, SCREEN_W - 140)
        y = random.randint(120, SCREEN_H - 130)
        sprites.append(SpriteObj(m, pygame.Rect(x, y, 70, 50)))

    return sprites


# -----------------------------
# CORE GAME
# -----------------------------
class TankGame:
    def __init__(self):
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Mk V Tank – Endless Survival Prototype")
        self.clock = pygame.time.Clock()

        self.state = GameState()
        self.state.breakdown_at_ms = self.now_ms() + self.random_breakdown_delay_ms()

        # Preload background images for each view
        self.bg: Dict[str, pygame.Surface] = {}
        self.bg[V_DRIVER] = load_image("driver.png", (SCREEN_W, SCREEN_H))
        self.bg[V_ENGINE] = load_image("engine.png", (SCREEN_W, SCREEN_H))
        self.bg[V_LEFT] = load_image("left.png", (SCREEN_W, SCREEN_H))
        self.bg[V_RIGHT] = load_image("right.png", (SCREEN_W, SCREEN_H))

        self.bg[V_OUT_DRIVER] = load_image("outdriver.png", (SCREEN_W, SCREEN_H))
        self.bg[V_OUT_LEFT] = load_image("outleft.png", (SCREEN_W, SCREEN_H))
        self.bg[V_OUT_RIGHT] = load_image("outright.png", (SCREEN_W, SCREEN_H))

        # Simple placeholder sprites
        self.sprite_zombie = make_placeholder_sprite("ZOMBIE", 80, 80, (120, 220, 140))
        self.sprite_fuel = make_placeholder_sprite("FUEL", 70, 50, (220, 200, 80))
        self.sprite_part = make_placeholder_sprite("PART", 70, 50, (160, 180, 220))
        self.sprite_shell = make_placeholder_sprite("SHELL", 70, 50, (220, 140, 90))

        # Outside sprites list for current outside view (regenerated each level)
        self.outside_sprites: Dict[str, List[SpriteObj]] = {
            V_OUT_DRIVER: [],
            V_OUT_LEFT: [],
            V_OUT_RIGHT: [],
        }

    def now_ms(self) -> int:
        return pygame.time.get_ticks()

    def random_breakdown_delay_ms(self) -> int:
        sec = random.randint(BREAKDOWN_MIN_SECONDS, BREAKDOWN_MAX_SECONDS)
        return sec * 1000

    def start_new_level(self, reason: str):
        # Engine breaks, tank stops moving
        self.state.in_level = True
        self.state.moving = False
        self.state.engine_broken = True

        # Generate new level pool
        zombies = random.randint(ZOMBIES_MIN, ZOMBIES_MAX)
        fuelcans = random.randint(FUELCANS_MIN, FUELCANS_MAX)
        shells = random.randint(SHELLS_MIN, SHELLS_MAX)
        parts = random.randint(PARTS_MIN, PARTS_MAX)  # guarantee at least 1

        self.state.level_pool = LevelPool(
            fuelcans=fuelcans,
            shells=shells,
            parts=parts,
            zombies=zombies,
        )

        # Regenerate outside sprites for each outside view
        for v in OUTSIDE_VIEWS:
            self.outside_sprites[v] = gen_outside_sprites_for_view(v, self.state.level_pool)

        self.show_popup(f"LEVEL STARTED: {reason}\nThe engine has broken down.\nScavenge if you need fuel/shells/parts.")

    def end_level_and_resume_driving(self):
        self.state.in_level = False
        self.state.engine_broken = False
        self.state.moving = True
        self.state.breakdown_at_ms = self.now_ms() + self.random_breakdown_delay_ms()
        # Outside sprites cleared until next level
        for v in OUTSIDE_VIEWS:
            self.outside_sprites[v] = []

    def show_popup(self, text: str):
        self.state.popup_text = text

    def close_popup(self):
        self.state.popup_text = None

    def begin_transition(self, to_view: str):
        if self.state.transitioning:
            return
        if to_view == self.state.view:
            return
        self.state.transitioning = True
        self.state.trans_from = self.state.view
        self.state.trans_to = to_view
        self.state.trans_t = 0.0

    def finish_transition(self):
        self.state.view = self.state.trans_to or self.state.view
        self.state.transitioning = False
        self.state.trans_from = None
        self.state.trans_to = None
        self.state.trans_t = 0.0

    def attempt_fix_engine(self):
        if not self.state.engine_broken:
            self.show_popup("The engine is not broken.")
            return
        if self.state.parts <= 0:
            self.show_popup("You do not have enough parts to fix the engine.")
            return
        self.state.parts -= 1
        self.state.engine_broken = False
        self.show_popup("Engine repaired.\nGo to Driver view and press START to get moving again.")

    def attempt_start(self):
        if self.state.moving:
            self.show_popup("Already moving.")
            return
        if self.state.engine_broken:
            self.show_popup("The engine is still broken.\nFix it from the ENGINE view.")
            return
        if self.state.fuel <= 0:
            self.show_popup("No fuel.\nYou must scavenge fuel before you can start.")
            return

        # Starting ends the level immediately (per your design)
        if self.state.in_level:
            self.end_level_and_resume_driving()
            self.show_popup("You start the engine.\nThe tank rumbles forward into the grey distance...")
        else:
            self.state.moving = True
            self.state.breakdown_at_ms = self.now_ms() + self.random_breakdown_delay_ms()

    def attempt_stop(self):
        if not self.state.moving:
            self.show_popup("Already stopped.")
            return
        # Stopping triggers a new level immediately
        self.start_new_level("Manual STOP")

    def outside_monotony_message(self):
        self.show_popup("The monotonous grey scenery of no man's land slips past.\nNothing to report.")

    def shoot_zombie_at(self, view: str, mouse_pos):
        if not self.state.in_level:
            return
        if view not in (V_OUT_LEFT, V_OUT_RIGHT):
            return
        if self.state.shells <= 0:
            self.show_popup("No shells left.")
            return

        sprites = self.outside_sprites[view]
        for i, sp in enumerate(sprites):
            if sp.kind == "ZOMBIE" and sp.rect.collidepoint(mouse_pos):
                # Spend shell, remove zombie from this view and reduce pool zombies
                self.state.shells -= 1
                sprites.pop(i)

                # Also reduce pool zombies and remove one zombie sprite from other outside views to keep them consistent-ish
                if self.state.level_pool and self.state.level_pool.zombies > 0:
                    self.state.level_pool.zombies -= 1

                for ov in OUTSIDE_VIEWS:
                    if ov == view:
                        continue
                    other = self.outside_sprites[ov]
                    for j, osp in enumerate(other):
                        if osp.kind == "ZOMBIE":
                            other.pop(j)
                            break

                return

    def open_scavenge_menu(self):
        if not self.state.in_level:
            self.show_popup("You can only scavenge during a level (when stopped).")
            return
        if self.state.crew <= 0:
            self.show_popup("No crew left.")
            return
        if self.state.level_pool is None or self.state.level_pool.total_items() <= 0:
            self.show_popup("Nothing left to scavenge here.")
            return

        # default selections
        self.state.scavenging_mode = "QUICK"
        self.state.scavenging_give_gun = False
        self.state.scavenging_confirm = True

    def close_scavenge_menu(self):
        self.state.scavenging_mode = None
        self.state.scavenging_give_gun = False
        self.state.scavenging_confirm = False

    def resolve_scavenge(self):
        if not self.state.scavenging_confirm or not self.state.scavenging_mode:
            return
        if not self.state.in_level or self.state.level_pool is None:
            self.close_scavenge_menu()
            return
        if self.state.crew <= 0:
            self.close_scavenge_menu()
            return

        mode = self.state.scavenging_mode
        cfg = SCAVENGE_MODES[mode]

        zombies = self.state.level_pool.zombies
        chance = cfg["base_return"] - zombies * ZOMBIE_PENALTY_PER
        gave_gun = False

        if self.state.scavenging_give_gun and self.state.guns > 0:
            gave_gun = True
            self.state.guns -= 1
            chance += GUN_BONUS

        chance = clamp(chance, 0.05, 0.95)
        success = (random.random() < chance)

        loot_frac = cfg["loot_frac"]
        pool = self.state.level_pool

        if success:
            # Determine how many “useful items” they bring back (as per fraction)
            total = pool.total_items()
            max_take = max(1, math.ceil(total * loot_frac))
            take_n = random.randint(1, max_take)

            gained_fuel = 0
            gained_shells = 0
            gained_parts = 0

            # Randomly pick item types from pool (weighted by remaining counts)
            for _ in range(take_n):
                choices = []
                if pool.fuelcans > 0:
                    choices.append("FUEL")
                if pool.shells > 0:
                    choices.append("SHELL")
                if pool.parts > 0:
                    choices.append("PART")
                if not choices:
                    break
                pick = random.choice(choices)
                if pick == "FUEL":
                    pool.fuelcans -= 1
                    gained_fuel += random.randint(FUELCAN_YIELD_MIN, FUELCAN_YIELD_MAX)
                elif pick == "SHELL":
                    pool.shells -= 1
                    gained_shells += 1
                else:
                    pool.parts -= 1
                    gained_parts += 1

            self.state.fuel += gained_fuel
            self.state.shells += gained_shells
            self.state.parts += gained_parts

            # If they had a gun, they return with it
            if gave_gun:
                self.state.guns += 1

            self.show_popup(
                f"Scavenge result ({mode}): SUCCESS\n"
                f"Return chance was {int(chance*100)}% (zombies: {zombies}{', with gun' if gave_gun else ''}).\n"
                f"Gained: +{gained_fuel} fuel, +{gained_shells} shells, +{gained_parts} parts."
            )
        else:
            # Crew member lost
            self.state.crew -= 1
            # If they had a gun, it is lost too (already removed from guns)
            self.show_popup(
                f"Scavenge result ({mode}): FAILED\n"
                f"Return chance was {int(chance*100)}% (zombies: {zombies}{', with gun' if gave_gun else ''}).\n"
                f"A crew member did not return."
                + ("\nThe gun is gone too." if gave_gun else "")
            )

            if self.state.crew <= 0:
                self.show_popup(
                    "All crew are gone.\n"
                    "The tank sits in the mud.\n"
                    "Game over."
                )

        self.close_scavenge_menu()

    # -----------------------------
    # UPDATE LOOP
    # -----------------------------
    def update(self, dt: float):
        # Transition update
        if self.state.transitioning:
            # fade out then in (0..1)
            self.state.trans_t += dt * 1.8
            if self.state.trans_t >= 1.0:
                self.finish_transition()

        # If popup is open, freeze most game logic (but we still animate transitions)
        if self.state.popup_text is not None:
            return

        # Driving behavior
        if self.state.moving:
            # fuel burn
            burn = FUEL_CONSUMED_PER_SECOND * dt
            if burn > 0:
                self.state.fuel = max(0, self.state.fuel - int(burn + 0.999))  # simple integer burn

            # Fuel empty triggers level
            if self.state.fuel <= 0:
                self.start_new_level("Fuel depleted")
                return

            # Random breakdown triggers level
            if self.now_ms() >= self.state.breakdown_at_ms:
                self.start_new_level("Random breakdown")
                return

    # -----------------------------
    # UI LAYOUT
    # -----------------------------
    def get_common_buttons(self) -> List[Button]:
        """
        View switching buttons (always present, but you can disable/adjust if desired).
        """
        btns: List[Button] = []
        x0, y0 = 15, 15
        w, h = 160, 42
        gap = 10

        # Internal view buttons
        btns.append(Button(pygame.Rect(x0, y0, w, h), "Driver", "GO_DRIVER"))
        btns.append(Button(pygame.Rect(x0, y0 + (h + gap)*1, w, h), "Engine", "GO_ENGINE"))
        btns.append(Button(pygame.Rect(x0, y0 + (h + gap)*2, w, h), "Left Gunner", "GO_LEFT"))
        btns.append(Button(pygame.Rect(x0, y0 + (h + gap)*3, w, h), "Right Gunner", "GO_RIGHT"))
        return btns

    def get_view_specific_buttons(self) -> List[Button]:
        btns: List[Button] = []
        right_x = SCREEN_W - 215
        y = 15
        w, h = 200, 44
        gap = 10

        v = self.state.view

        # Driver view controls
        if v == V_DRIVER:
            btns.append(Button(pygame.Rect(right_x, y, w, h), "Look Out (Driver)", "LOOK_OUT_DRIVER"))
            y += h + gap
            btns.append(Button(pygame.Rect(right_x, y, w, h), "START", "START"))
            y += h + gap
            btns.append(Button(pygame.Rect(right_x, y, w, h), "STOP (New Level)", "STOP"))
            y += h + gap

        # Engine view controls
        if v == V_ENGINE:
            btns.append(Button(pygame.Rect(right_x, y, w, h), "Fix Engine (1 part)", "FIX_ENGINE",
                               enabled=self.state.in_level))
            y += h + gap
            btns.append(Button(pygame.Rect(right_x, y, w, h), "Send Scavenger", "SCAVENGE",
                               enabled=self.state.in_level))
            y += h + gap

        # Gunner internal views: look out buttons
        if v == V_LEFT:
            btns.append(Button(pygame.Rect(right_x, y, w, h), "Look Out (Left)", "LOOK_OUT_LEFT"))
            y += h + gap
        if v == V_RIGHT:
            btns.append(Button(pygame.Rect(right_x, y, w, h), "Look Out (Right)", "LOOK_OUT_RIGHT"))
            y += h + gap

        # Outside views: back buttons
        if v == V_OUT_DRIVER:
            btns.append(Button(pygame.Rect(right_x, y, w, h), "Back Inside", "BACK_INSIDE_DRIVER"))
            y += h + gap
        if v == V_OUT_LEFT:
            btns.append(Button(pygame.Rect(right_x, y, w, h), "Back Inside", "BACK_INSIDE_LEFT"))
            y += h + gap
        if v == V_OUT_RIGHT:
            btns.append(Button(pygame.Rect(right_x, y, w, h), "Back Inside", "BACK_INSIDE_RIGHT"))
            y += h + gap

        return btns

    # -----------------------------
    # EVENT HANDLING
    # -----------------------------
    def handle_action(self, action: str):
        if self.state.transitioning:
            return

        # If popup open, only allow closing popup
        if self.state.popup_text is not None:
            if action == "POPUP_OK":
                self.close_popup()
            return

        # Scavenging modal open: handle its actions only
        if self.state.scavenging_confirm:
            if action.startswith("SCAV_MODE_"):
                self.state.scavenging_mode = action.replace("SCAV_MODE_", "")
                return
            if action == "SCAV_TOGGLE_GUN":
                self.state.scavenging_give_gun = not self.state.scavenging_give_gun
                return
            if action == "SCAV_GO":
                self.resolve_scavenge()
                return
            if action == "SCAV_CANCEL":
                self.close_scavenge_menu()
                return

        # View nav
        if action == "GO_DRIVER":
            self.begin_transition(V_DRIVER)
        elif action == "GO_ENGINE":
            self.begin_transition(V_ENGINE)
        elif action == "GO_LEFT":
            self.begin_transition(V_LEFT)
        elif action == "GO_RIGHT":
            self.begin_transition(V_RIGHT)

        # Look out
        elif action == "LOOK_OUT_DRIVER":
            if self.state.moving:
                self.outside_monotony_message()
            else:
                self.begin_transition(V_OUT_DRIVER)
        elif action == "LOOK_OUT_LEFT":
            if self.state.moving:
                self.outside_monotony_message()
            else:
                self.begin_transition(V_OUT_LEFT)
        elif action == "LOOK_OUT_RIGHT":
            if self.state.moving:
                self.outside_monotony_message()
            else:
                self.begin_transition(V_OUT_RIGHT)

        # Back inside
        elif action == "BACK_INSIDE_DRIVER":
            self.begin_transition(V_DRIVER)
        elif action == "BACK_INSIDE_LEFT":
            self.begin_transition(V_LEFT)
        elif action == "BACK_INSIDE_RIGHT":
            self.begin_transition(V_RIGHT)

        # Start/Stop/Fix/Scavenge
        elif action == "START":
            self.attempt_start()
        elif action == "STOP":
            self.attempt_stop()
        elif action == "FIX_ENGINE":
            self.attempt_fix_engine()
        elif action == "SCAVENGE":
            self.open_scavenge_menu()

    def handle_click(self, mouse_pos):
        # Popup click handling
        if self.state.popup_text is not None:
            # OK button center-bottom
            ok_rect = pygame.Rect(SCREEN_W//2 - 80, SCREEN_H//2 + 120, 160, 45)
            if ok_rect.collidepoint(mouse_pos):
                self.handle_action("POPUP_OK")
            return

        # Scavenging modal click handling
        if self.state.scavenging_confirm:
            # mode buttons
            x = SCREEN_W//2 - 260
            y = SCREEN_H//2 - 80
            w = 170
            h = 44
            gap = 12
            modes = ["QUICK", "MODERATE", "GREEDY"]
            for i, m in enumerate(modes):
                r = pygame.Rect(x + i*(w+gap), y, w, h)
                if r.collidepoint(mouse_pos):
                    self.handle_action(f"SCAV_MODE_{m}")
                    return

            gun_r = pygame.Rect(SCREEN_W//2 - 160, SCREEN_H//2 - 20, 320, 44)
            if gun_r.collidepoint(mouse_pos):
                self.handle_action("SCAV_TOGGLE_GUN")
                return

            go_r = pygame.Rect(SCREEN_W//2 - 170, SCREEN_H//2 + 50, 160, 48)
            cancel_r = pygame.Rect(SCREEN_W//2 + 10, SCREEN_H//2 + 50, 160, 48)
            if go_r.collidepoint(mouse_pos):
                self.handle_action("SCAV_GO")
                return
            if cancel_r.collidepoint(mouse_pos):
                self.handle_action("SCAV_CANCEL")
                return
            return

        # Outside zombie shooting (left/right)
        if self.state.view in (V_OUT_LEFT, V_OUT_RIGHT) and self.state.in_level:
            self.shoot_zombie_at(self.state.view, mouse_pos)

        # Regular buttons
        buttons = self.get_common_buttons() + self.get_view_specific_buttons()
        for b in buttons:
            if b.hit(mouse_pos):
                self.handle_action(b.action)
                return

    # -----------------------------
    # RENDERING
    # -----------------------------
    def draw_hud(self):
        # Top status strip
        bar = pygame.Rect(0, 0, SCREEN_W, 70)
        pygame.draw.rect(self.screen, (15, 15, 15), bar)
        pygame.draw.line(self.screen, (60, 60, 60), (0, 70), (SCREEN_W, 70), 2)

        status1 = f"Fuel: {self.state.fuel} | Shells: {self.state.shells} | Guns: {self.state.guns} | Crew: {self.state.crew} | Parts: {self.state.parts}"
        status2 = f"{'DRIVING' if self.state.moving else 'STOPPED'} | {'IN LEVEL' if self.state.in_level else 'TRAVERSING'} | View: {self.state.view}"
        draw_text(self.screen, status1, (210, 14), WHITE, FONT)
        draw_text(self.screen, status2, (210, 40), (200, 200, 200), FONT)

        # If in level, show pool summary
        if self.state.level_pool:
            pool = self.state.level_pool
            pool_txt = f"Level pool → Fuelcans:{pool.fuelcans} Shells:{pool.shells} Parts:{pool.parts} Zombies:{pool.zombies}"
            draw_text(self.screen, pool_txt, (210, 66), (170, 170, 170), FONT)

    def draw_buttons(self):
        buttons = self.get_common_buttons() + self.get_view_specific_buttons()
        for b in buttons:
            b.draw(self.screen)

    def draw_outside_sprites(self):
        sprites = self.outside_sprites.get(self.state.view, [])
        for sp in sprites:
            if sp.kind == "ZOMBIE":
                self.screen.blit(self.sprite_zombie, sp.rect.topleft)
            elif sp.kind == "FUEL":
                self.screen.blit(self.sprite_fuel, sp.rect.topleft)
            elif sp.kind == "PART":
                self.screen.blit(self.sprite_part, sp.rect.topleft)
            elif sp.kind == "SHELL":
                self.screen.blit(self.sprite_shell, sp.rect.topleft)

        # Instruction line for shooting
        if self.state.view in (V_OUT_LEFT, V_OUT_RIGHT) and self.state.in_level:
            draw_text(self.screen, "Click a zombie to fire (costs 1 shell).", (230, 90), YELLOW, FONT)

    def draw_popup(self, text: str):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(SCREEN_W//2 - 340, SCREEN_H//2 - 170, 680, 360)
        pygame.draw.rect(self.screen, (30, 30, 30), box, border_radius=16)
        pygame.draw.rect(self.screen, (120, 120, 120), box, 3, border_radius=16)

        # Wrap text
        lines = []
        for para in text.split("\n"):
            words = para.split(" ")
            line = ""
            for w in words:
                test = (line + " " + w).strip()
                if FONT.size(test)[0] <= box.width - 40:
                    line = test
                else:
                    lines.append(line)
                    line = w
            if line:
                lines.append(line)
            lines.append("")  # paragraph gap

        y = box.top + 24
        for ln in lines[:12]:
            draw_text(self.screen, ln, (box.left + 24, y), WHITE, FONT)
            y += 26

        ok_rect = pygame.Rect(SCREEN_W//2 - 80, SCREEN_H//2 + 120, 160, 45)
        pygame.draw.rect(self.screen, (200, 200, 200), ok_rect, border_radius=10)
        pygame.draw.rect(self.screen, DARK, ok_rect, 2, border_radius=10)
        draw_text(self.screen, "OK", ok_rect.move(0, 0).topleft, BLACK, FONT_BIG)
        # center OK text
        ok_lbl = FONT_BIG.render("OK", True, BLACK)
        self.screen.blit(ok_lbl, ok_lbl.get_rect(center=ok_rect.center))

    def draw_scavenge_modal(self):
        pool = self.state.level_pool
        if pool is None:
            return

        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        box = pygame.Rect(SCREEN_W//2 - 420, SCREEN_H//2 - 180, 840, 380)
        pygame.draw.rect(self.screen, (25, 25, 25), box, border_radius=16)
        pygame.draw.rect(self.screen, (120, 120, 120), box, 3, border_radius=16)

        draw_text(self.screen, "Send 1 crew member to scavenge", (box.left + 22, box.top + 18), WHITE, FONT_BIG)

        # mode buttons
        x = SCREEN_W//2 - 260
        y = SCREEN_H//2 - 80
        w = 170
        h = 44
        gap = 12

        for i, m in enumerate(["QUICK", "MODERATE", "GREEDY"]):
            r = pygame.Rect(x + i*(w+gap), y, w, h)
            selected = (self.state.scavenging_mode == m)
            pygame.draw.rect(self.screen, (220, 220, 220) if selected else (160, 160, 160), r, border_radius=10)
            pygame.draw.rect(self.screen, DARK, r, 2, border_radius=10)
            label = f"{m.title()}"
            lbl = FONT.render(label, True, BLACK)
            self.screen.blit(lbl, lbl.get_rect(center=r.center))

        # give gun toggle
        gun_r = pygame.Rect(SCREEN_W//2 - 160, SCREEN_H//2 - 20, 320, 44)
        pygame.draw.rect(self.screen, (180, 220, 190) if self.state.scavenging_give_gun else (160, 160, 160), gun_r, border_radius=10)
        pygame.draw.rect(self.screen, DARK, gun_r, 2, border_radius=10)
        gun_txt = f"Give gun (+{int(GUN_BONUS*100)}% chance) [{ 'YES' if self.state.scavenging_give_gun else 'NO' }]"
        lbl = FONT.render(gun_txt, True, BLACK)
        self.screen.blit(lbl, lbl.get_rect(center=gun_r.center))

        # compute preview chance
        mode = self.state.scavenging_mode or "QUICK"
        cfg = SCAVENGE_MODES[mode]
        chance = cfg["base_return"] - pool.zombies * ZOMBIE_PENALTY_PER
        if self.state.scavenging_give_gun and self.state.guns > 0:
            chance += GUN_BONUS
        chance = clamp(chance, 0.05, 0.95)

        preview = (
            f"Zombies visible: {pool.zombies} | Base return: {int(cfg['base_return']*100)}%\n"
            f"Estimated return chance: {int(chance*100)}%\n"
            f"Loot fraction: up to {int(cfg['loot_frac']*100)}% of remaining items"
        )
        draw_text(self.screen, preview, (box.left + 22, SCREEN_H//2 + 20), (210, 210, 210), FONT)

        # go/cancel
        go_r = pygame.Rect(SCREEN_W//2 - 170, SCREEN_H//2 + 120, 160, 48)
        cancel_r = pygame.Rect(SCREEN_W//2 + 10, SCREEN_H//2 + 120, 160, 48)

        pygame.draw.rect(self.screen, (200, 200, 200), go_r, border_radius=10)
        pygame.draw.rect(self.screen, DARK, go_r, 2, border_radius=10)
        pygame.draw.rect(self.screen, (200, 200, 200), cancel_r, border_radius=10)
        pygame.draw.rect(self.screen, DARK, cancel_r, 2, border_radius=10)

        self.screen.blit(FONT_BIG.render("GO", True, BLACK), FONT_BIG.render("GO", True, BLACK).get_rect(center=go_r.center))
        self.screen.blit(FONT_BIG.render("CANCEL", True, BLACK), FONT_BIG.render("CANCEL", True, BLACK).get_rect(center=cancel_r.center))

        # warnings
        if self.state.scavenging_give_gun and self.state.guns <= 0:
            draw_text(self.screen, "No guns available to give.", (box.left + 22, box.bottom - 44), RED, FONT)

    def draw_transition(self):
        # Simple fade to black between views
        if not self.state.transitioning:
            return

        t = self.state.trans_t  # 0..1
        # ease-in-out
        alpha = int(255 * clamp(t, 0.0, 1.0))
        veil = pygame.Surface((SCREEN_W, SCREEN_H))
        veil.fill(BLACK)
        veil.set_alpha(alpha)
        self.screen.blit(veil, (0, 0))

    def render(self):
        # Draw background based on current view
        self.screen.blit(self.bg[self.state.view], (0, 0))

        # Draw outside sprites only when actually in outside views during level
        if self.state.view in OUTSIDE_VIEWS and self.state.in_level:
            self.draw_outside_sprites()

        # HUD & buttons
        self.draw_hud()
        self.draw_buttons()

        # If in outside views while DRIVING, show subtle hint
        if self.state.view in OUTSIDE_VIEWS and self.state.moving:
            draw_text(self.screen, "(You are moving.)", (230, 92), (180, 180, 180), FONT)

        # Modal overlays
        if self.state.scavenging_confirm:
            self.draw_scavenge_modal()

        if self.state.popup_text is not None:
            self.draw_popup(self.state.popup_text)

        # Transition overlay last
        self.draw_transition()

        pygame.display.flip()

    # -----------------------------
    # MAIN LOOP
    # -----------------------------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_click(event.pos)

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

            self.update(dt)
            self.render()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    # Ensure asset folder exists (for user convenience)
    if not os.path.exists(ASSET_DIR):
        os.makedirs(ASSET_DIR, exist_ok=True)

    TankGame().run()
