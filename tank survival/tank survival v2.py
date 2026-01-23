import os
import sys
import random
import math
import pygame

# ============================================================
# CONFIG (tweak these near the top, as requested)
# ============================================================

SCREEN_W, SCREEN_H = 1100, 650
FPS = 60

STARTING_FUEL = 200
FUEL_CONSUMED_PER_SEC = 2.0

STARTING_SHELLS = 6
STARTING_GUNS = 4
STARTING_CREW = 4

# Level breakdown random time while driving (seconds)
BREAKDOWN_MIN = 30
BREAKDOWN_MAX = 180

# Scavenge parameters
FUEL_PICKUP_MIN = 10
FUEL_PICKUP_MAX = 100

# Spawn counts per level (can tune later)
MIN_PARTS_PER_LEVEL = 1
EXTRA_PARTS_MAX = 2

FUEL_CANS_MIN = 1
FUEL_CANS_MAX = 4

SHELLS_PICKUPS_MIN = 0
SHELLS_PICKUPS_MAX = 3

ZOMBIES_MIN = 0
ZOMBIES_MAX = 6

# Click-to-shoot settings
SHELLS_PER_SHOT = 1

# Fade transition speed (alpha per frame-ish)
FADE_SPEED = 18

ASSET_DIR = "assets"

# ============================================================
# Asset filenames (replace with your own later)
# ============================================================
# Inside tank views (4)
INSIDE_DRIVER = "driver.png"
INSIDE_ENGINE = "engine.png"
INSIDE_CREW = "crew.png"
INSIDE_AMMO = "ammo.png"

# Outside slit views (3)
OUTSIDE_DRIVER = "outside_driver.png"
OUTSIDE_LEFT = "outside_left.png"
OUTSIDE_RIGHT = "outside_right.png"

# Placeholder sprites (you can replace with actual pngs too)
SPR_FUEL = "spr_fuel.png"
SPR_PART = "spr_part.png"
SPR_SHELLS = "spr_shells.png"
SPR_ZOMBIE = "spr_zombie.png"

# ============================================================
# Helpers
# ============================================================

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def load_image_scaled(path, size, fallback_color=(70, 70, 70), label=None):
    """Loads an image; if missing, creates a colored surface with label text."""
    full = os.path.join(ASSET_DIR, path)
    surf = pygame.Surface(size).convert()
    if os.path.exists(full):
        img = pygame.image.load(full).convert_alpha()
        surf = pygame.transform.smoothscale(img, size).convert_alpha()
        return surf
    else:
        surf.fill(fallback_color)
        if label:
            font = pygame.font.SysFont(None, 42)
            txt = font.render(label, True, (240, 240, 240))
            rect = txt.get_rect(center=(size[0] // 2, size[1] // 2))
            surf.blit(txt, rect)
        return surf.convert()

def load_sprite(path, fallback_color, label):
    size = (60, 60)
    return load_image_scaled(path, size, fallback_color=fallback_color, label=label)

# ============================================================
# UI: Button + Popup
# ============================================================

class Button:
    def __init__(self, rect, text, on_click, font, bg=(40, 40, 40), fg=(240, 240, 240)):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.on_click = on_click
        self.font = font
        self.bg = bg
        self.fg = fg
        self.hover = False
        self.enabled = True

    def handle_event(self, e):
        if not self.enabled:
            return
        if e.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.rect.collidepoint(e.pos):
                self.on_click()

    def draw(self, screen):
        c = (60, 60, 60) if self.hover else self.bg
        if not self.enabled:
            c = (25, 25, 25)
        pygame.draw.rect(screen, c, self.rect, border_radius=8)
        pygame.draw.rect(screen, (120, 120, 120), self.rect, width=2, border_radius=8)

        txt = self.font.render(self.text, True, self.fg if self.enabled else (120, 120, 120))
        r = txt.get_rect(center=self.rect.center)
        screen.blit(txt, r)

class Popup:
    def __init__(self):
        self.msg = ""
        self.timer = 0.0

    def show(self, msg, seconds=2.0):
        self.msg = msg
        self.timer = seconds

    def update(self, dt):
        if self.timer > 0:
            self.timer -= dt
            if self.timer <= 0:
                self.msg = ""

    def draw(self, screen, font):
        if not self.msg:
            return
        pad = 12
        txt = font.render(self.msg, True, (255, 255, 255))
        r = txt.get_rect()
        box = pygame.Rect(0, 0, r.width + pad * 2, r.height + pad * 2)
        box.midbottom = (SCREEN_W // 2, SCREEN_H - 12)
        pygame.draw.rect(screen, (0, 0, 0), box, border_radius=10)
        pygame.draw.rect(screen, (160, 160, 160), box, width=2, border_radius=10)
        screen.blit(txt, txt.get_rect(center=box.center))

# ============================================================
# Level content (outside view spawns)
# ============================================================

class SpawnItem:
    def __init__(self, kind, pos, sprite):
        self.kind = kind  # "fuel", "part", "shells"
        self.pos = pygame.Vector2(pos)
        self.sprite = sprite
        self.rect = self.sprite.get_rect(center=pos)
        self.collected = False
        # For fuel, store amount
        self.amount = None

class Zombie:
    def __init__(self, pos, sprite):
        self.pos = pygame.Vector2(pos)
        self.sprite = sprite
        self.rect = self.sprite.get_rect(center=pos)
        self.alive = True

# ============================================================
# Game core
# ============================================================

VIEW_DRIVER_INSIDE = "driver_inside"
VIEW_ENGINE = "engine"
VIEW_CREW = "crew"
VIEW_AMMO = "ammo"

VIEW_OUT_DRIVER = "out_driver"
VIEW_OUT_LEFT = "out_left"
VIEW_OUT_RIGHT = "out_right"

# Which views count as "outside slit"
OUTSIDE_VIEWS = {VIEW_OUT_DRIVER, VIEW_OUT_LEFT, VIEW_OUT_RIGHT}

class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("MkV Endless Tank Survival (Prototype)")
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont(None, 28)
        self.bigfont = pygame.font.SysFont(None, 44)

        # Load view backgrounds
        self.bg_driver_inside = load_image_scaled(INSIDE_DRIVER, (SCREEN_W, SCREEN_H),
                                                  fallback_color=(40, 30, 30), label="INSIDE: DRIVER")
        self.bg_engine = load_image_scaled(INSIDE_ENGINE, (SCREEN_W, SCREEN_H),
                                           fallback_color=(30, 40, 30), label="INSIDE: ENGINE")
        self.bg_crew = load_image_scaled(INSIDE_CREW, (SCREEN_W, SCREEN_H),
                                         fallback_color=(30, 30, 40), label="INSIDE: CREW")
        self.bg_ammo = load_image_scaled(INSIDE_AMMO, (SCREEN_W, SCREEN_H),
                                         fallback_color=(45, 35, 20), label="INSIDE: AMMO")

        self.bg_out_driver = load_image_scaled(OUTSIDE_DRIVER, (SCREEN_W, SCREEN_H),
                                               fallback_color=(60, 60, 60), label="OUTSIDE: DRIVER SLIT")
        self.bg_out_left = load_image_scaled(OUTSIDE_LEFT, (SCREEN_W, SCREEN_H),
                                             fallback_color=(55, 55, 65), label="OUTSIDE: LEFT SLIT")
        self.bg_out_right = load_image_scaled(OUTSIDE_RIGHT, (SCREEN_W, SCREEN_H),
                                              fallback_color=(65, 55, 55), label="OUTSIDE: RIGHT SLIT")

        # Load sprites
        self.spr_fuel = load_sprite(SPR_FUEL, (70, 140, 70), "FUEL")
        self.spr_part = load_sprite(SPR_PART, (140, 140, 70), "PART")
        self.spr_shells = load_sprite(SPR_SHELLS, (70, 110, 160), "SHELLS")
        self.spr_zombie = load_sprite(SPR_ZOMBIE, (140, 70, 70), "Z")

        # State
        self.popup = Popup()
        self.running = True
        self.game_over = False

        # Resources / stats
        self.fuel = STARTING_FUEL
        self.shells = STARTING_SHELLS
        self.guns = STARTING_GUNS
        self.crew = STARTING_CREW
        self.parts = 0

        # Movement/level state
        self.driving = True
        self.engine_broken = False
        self.breakdown_timer = self._new_breakdown_timer()
        self.fuel_accum = 0.0  # for fractional fuel consumption

        # Current view
        self.view = VIEW_DRIVER_INSIDE

        # Fade transition
        self.fading = False
        self.fade_alpha = 0
        self.fade_phase = "out"  # "out" then "in"
        self.pending_view = None

        # Level content: per outside view
        self.level_items = {VIEW_OUT_DRIVER: [], VIEW_OUT_LEFT: [], VIEW_OUT_RIGHT: []}
        self.level_zombies = {VIEW_OUT_DRIVER: [], VIEW_OUT_LEFT: [], VIEW_OUT_RIGHT: []}
        self.level_active = False  # True when engine broken & we are scavenging/fixing

        # Scavenge interaction state
        self.scavenge_mode = False
        self.selected_risk = None  # "quick", "moderate", "greedy"
        self.selected_give_gun = None  # True/False

        # UI (rebuilt each frame based on view/state, but we keep objects around)
        self.buttons = []

        # Start: if driving, the outside slits while driving should show "monotonous scenery"
        # but you still can swap views.

    def _new_breakdown_timer(self):
        return random.uniform(BREAKDOWN_MIN, BREAKDOWN_MAX)

    def start_fade_to(self, new_view):
        if self.fading:
            return
        self.fading = True
        self.fade_alpha = 0
        self.fade_phase = "out"
        self.pending_view = new_view

    def begin_level(self, reason):
        """Engine breaks down -> start a level with spawns."""
        self.level_active = True
        self.engine_broken = True
        self.driving = False
        self.scavenge_mode = False
        self.selected_risk = None
        self.selected_give_gun = None

        # Generate new level content
        self._generate_level_spawns()

        if reason == "breakdown":
            self.popup.show("The engine sputters and dies. You've broken down.", 2.5)
        elif reason == "fuel":
            self.popup.show("The tank coughs and stops. You're out of fuel.", 2.5)
        elif reason == "manual_stop":
            self.popup.show("You stop the tank. New trouble begins immediately.", 2.5)

        # Force inside driver view for coherence if you want:
        # self.start_fade_to(VIEW_DRIVER_INSIDE)

    def end_level_and_resume_driving(self):
        """Called when player fixes engine & presses start driving."""
        self.level_active = False
        self.engine_broken = False
        self.driving = True
        self.breakdown_timer = self._new_breakdown_timer()
        self.popup.show("The engine rumbles back to life. Moving again...", 2.0)

    def _generate_level_spawns(self):
        # Clear old
        for k in self.level_items:
            self.level_items[k] = []
        for k in self.level_zombies:
            self.level_zombies[k] = []

        # Decide totals for level, then distribute among 3 outside views
        total_parts = MIN_PARTS_PER_LEVEL + random.randint(0, EXTRA_PARTS_MAX)
        total_fuel = random.randint(FUEL_CANS_MIN, FUEL_CANS_MAX)
        total_shells = random.randint(SHELLS_PICKUPS_MIN, SHELLS_PICKUPS_MAX)
        total_zombies = random.randint(ZOMBIES_MIN, ZOMBIES_MAX)

        # helper to random view
        views = [VIEW_OUT_DRIVER, VIEW_OUT_LEFT, VIEW_OUT_RIGHT]

        def rand_pos():
            # keep in view center-ish; avoid UI strip at bottom
            x = random.randint(120, SCREEN_W - 120)
            y = random.randint(110, SCREEN_H - 140)
            return (x, y)

        # Items
        for _ in range(total_parts):
            v = random.choice(views)
            it = SpawnItem("part", rand_pos(), self.spr_part)
            self.level_items[v].append(it)

        for _ in range(total_fuel):
            v = random.choice(views)
            it = SpawnItem("fuel", rand_pos(), self.spr_fuel)
            it.amount = random.randint(FUEL_PICKUP_MIN, FUEL_PICKUP_MAX)
            self.level_items[v].append(it)

        for _ in range(total_shells):
            v = random.choice(views)
            it = SpawnItem("shells", rand_pos(), self.spr_shells)
            # shells amount could be variable; keep simple:
            it.amount = random.randint(1, 3)
            self.level_items[v].append(it)

        # Zombies
        for _ in range(total_zombies):
            v = random.choice(views)
            z = Zombie(rand_pos(), self.spr_zombie)
            self.level_zombies[v].append(z)

    def total_zombies_alive(self):
        c = 0
        for v in self.level_zombies:
            c += sum(1 for z in self.level_zombies[v] if z.alive)
        return c

    def handle_shot_click(self, pos):
        """Only meaningful in gunner outside views."""
        if not self.level_active:
            # driving -> outside gives monotonous message
            self.popup.show("The monotonous grey scenery of no man's land slips past. Nothing to report.", 2.0)
            return

        if self.shells < SHELLS_PER_SHOT:
            self.popup.show("Click. You're out of shells.", 1.8)
            return

        # Only shoot zombies in the current view
        zombies = self.level_zombies.get(self.view, [])
        for z in zombies:
            if z.alive and z.rect.collidepoint(pos):
                self.shells -= SHELLS_PER_SHOT
                z.alive = False
                self.popup.show("BOOM. Zombie down.", 1.2)
                return

        # Clicking empty space can still be a shot if you want; here we don't spend shells.
        self.popup.show("No target.", 1.0)

    def handle_item_click(self, pos):
        """Collect fuel/parts/shells in outside views during a level."""
        if not self.level_active:
            self.popup.show("The monotonous grey scenery of no man's land slips past. Nothing to report.", 2.0)
            return

        items = self.level_items.get(self.view, [])
        for it in items:
            if not it.collected and it.rect.collidepoint(pos):
                it.collected = True
                if it.kind == "fuel":
                    gained = it.amount or 0
                    self.fuel += gained
                    self.popup.show(f"Collected fuel (+{gained}).", 1.6)
                elif it.kind == "part":
                    self.parts += 1
                    self.popup.show("Collected parts (+1).", 1.6)
                elif it.kind == "shells":
                    gained = it.amount or 0
                    self.shells += gained
                    self.popup.show(f"Collected shells (+{gained}).", 1.6)
                return

    def attempt_fix_engine(self):
        if self.parts <= 0:
            self.popup.show("You do not have enough parts to fix the engine.", 2.2)
            return
        # consumes exactly 1 part per fix
        self.parts -= 1
        self.engine_broken = False
        self.popup.show("You repair the engine. Go to Driver and start moving.", 2.2)

    def attempt_start_driving(self):
        if self.level_active:
            # During a level, you can only start if engine is not broken
            if self.engine_broken:
                self.popup.show("The engine is still broken.", 1.8)
                return
            # Fuel check
            if self.fuel <= 0:
                self.popup.show("No fuel. You can't move.", 1.8)
                return
            self.end_level_and_resume_driving()
        else:
            # Already driving state
            if self.fuel <= 0:
                self.popup.show("No fuel. You can't move.", 1.8)
                return
            self.driving = True

    def stop_driving_now(self):
        if self.driving:
            self.begin_level("manual_stop")

    def open_scavenge_menu(self):
        if not self.level_active:
            self.popup.show("You can only scavenge when broken down.", 2.0)
            return
        if self.crew <= 0:
            self.popup.show("No crew left to send.", 2.0)
            return
        self.scavenge_mode = True
        self.selected_risk = None
        self.selected_give_gun = None

    def do_scavenge(self, risk, give_gun):
        """Resolve a single scavenging attempt by 1 crew member."""
        if self.crew <= 0:
            self.popup.show("No crew left.", 2.0)
            return

        # Compute how many useful items exist across ALL outside views (not collected)
        remaining_items = []
        for v in self.level_items:
            for it in self.level_items[v]:
                if not it.collected and it.kind in ("fuel", "part", "shells"):
                    remaining_items.append(it)

        if not remaining_items:
            self.popup.show("There's nothing useful left to scavenge.", 2.0)
            return

        # Determine cap based on risk
        if risk == "quick":
            base_return = 0.75
            frac = 1/3
        elif risk == "moderate":
            base_return = 0.50
            frac = 0.50
        else:  # greedy
            base_return = 0.33
            frac = 1.0

        zombies_alive = self.total_zombies_alive()

        # Zombie impact: more zombies reduces chance. Tuned to be simple and adjustable.
        # Each zombie reduces by 0.06 (6%), clamped.
        zombie_penalty = 0.06 * zombies_alive

        # Gun bonus if you give one (but you risk losing it if crew doesn't return)
        gun_bonus = 0.18 if give_gun else 0.0

        # If trying to give a gun but none left:
        if give_gun and self.guns <= 0:
            self.popup.show("No guns left to give. Sending them unarmed.", 2.0)
            give_gun = False
            gun_bonus = 0.0

        # Final chance
        chance = base_return - zombie_penalty + gun_bonus
        chance = clamp(chance, 0.05, 0.95)

        # Decide how many items they can potentially grab
        max_take = max(1, math.floor(len(remaining_items) * frac))
        take_count = random.randint(1, max_take)

        # Pick the items they find (random)
        found = random.sample(remaining_items, k=take_count)

        # Resolve survival
        survives = (random.random() < chance)

        # Mark found items as collected if survives (they bring them back)
        if survives:
            # Collect items into inventory
            fuel_gain = 0
            parts_gain = 0
            shells_gain = 0
            for it in found:
                it.collected = True
                if it.kind == "fuel":
                    fuel_gain += it.amount or 0
                elif it.kind == "part":
                    parts_gain += 1
                elif it.kind == "shells":
                    shells_gain += it.amount or 0

            self.fuel += fuel_gain
            self.parts += parts_gain
            self.shells += shells_gain

            msg_bits = []
            if fuel_gain: msg_bits.append(f"fuel +{fuel_gain}")
            if parts_gain: msg_bits.append(f"parts +{parts_gain}")
            if shells_gain: msg_bits.append(f"shells +{shells_gain}")
            got = ", ".join(msg_bits) if msg_bits else "nothing useful"
            self.popup.show(f"Scavenger returned! Got {got}.", 3.0)

            # If you gave a gun, they return with it (no loss)
        else:
            # Crew dies (lost)
            self.crew -= 1

            # If you gave a gun, lose it too
            if give_gun and self.guns > 0:
                self.guns -= 1

            if self.crew <= 0:
                self.game_over = True
                self.popup.show("Your last crew member never returned. Game Over.", 4.0)
            else:
                lostgun = " and the gun" if give_gun else ""
                self.popup.show(f"The scavenger never returned... You lost a crew member{lostgun}.", 3.5)

        # Exit scavenge menu after an attempt (simple loop)
        self.scavenge_mode = False
        self.selected_risk = None
        self.selected_give_gun = None

    def build_ui(self):
        """Rebuild buttons based on current view/state."""
        self.buttons = []
        y = SCREEN_H - 56
        x = 12
        w = 165
        h = 44
        gap = 10

        def add(text, cb, enabled=True, width=w):
            nonlocal x
            b = Button((x, y, width, h), text, cb, self.font)
            b.enabled = enabled
            self.buttons.append(b)
            x += width + gap

        # Global navigation buttons
        add("Driver (Inside)", lambda: self.start_fade_to(VIEW_DRIVER_INSIDE))
        add("Engine", lambda: self.start_fade_to(VIEW_ENGINE))
        add("Crew", lambda: self.start_fade_to(VIEW_CREW))
        add("Ammo", lambda: self.start_fade_to(VIEW_AMMO))

        # Outside views
        add("Out: Driver", lambda: self.start_fade_to(VIEW_OUT_DRIVER))
        add("Out: Left", lambda: self.start_fade_to(VIEW_OUT_LEFT))
        add("Out: Right", lambda: self.start_fade_to(VIEW_OUT_RIGHT))

        # View-specific controls (right side row)
        # We'll stack another row above for view actions
        y2 = SCREEN_H - 110
        x2 = 12

        def add2(text, cb, enabled=True, width=210):
            nonlocal x2
            b = Button((x2, y2, width, h), text, cb, self.font)
            b.enabled = enabled
            self.buttons.append(b)
            x2 += width + gap

        # Driver inside controls
        if self.view == VIEW_DRIVER_INSIDE:
            if self.driving and not self.level_active:
                add2("Stop (Start a Level)", self.stop_driving_now, enabled=True)
            else:
                # Level active or already stopped: Start depends on fixed + fuel
                can_start = (not self.engine_broken) and (self.fuel > 0)
                add2("Start Driving", self.attempt_start_driving, enabled=can_start)

        # Engine controls
        if self.view == VIEW_ENGINE:
            add2("Fix Engine (1 Part)", self.attempt_fix_engine, enabled=self.level_active)

        # Scavenge controls (available during level from any view)
        if self.level_active:
            add2("Scavenge", self.open_scavenge_menu, enabled=(self.crew > 0))

        # If in scavenge mode, add risk buttons (third row)
        if self.scavenge_mode:
            y3 = SCREEN_H - 164
            x3 = 12

            def add3(text, cb, enabled=True, width=200):
                nonlocal x3
                b = Button((x3, y3, width, h), text, cb, self.font)
                b.enabled = enabled
                self.buttons.append(b)
                x3 += width + gap

            add3("Quick (75% base)", lambda: self._select_scavenge_risk("quick"))
            add3("Moderate (50% base)", lambda: self._select_scavenge_risk("moderate"))
            add3("Greedy (33% base)", lambda: self._select_scavenge_risk("greedy"))

            # Fourth row: gun choice + confirm
            y4 = SCREEN_H - 218
            x4 = 12

            def add4(text, cb, enabled=True, width=240):
                nonlocal x4
                b = Button((x4, y4, width, h), text, cb, self.font)
                b.enabled = enabled
                self.buttons.append(b)
                x4 += width + gap

            add4("Send Unarmed", lambda: self._select_scavenge_gun(False))
            add4("Give Gun (+chance)", lambda: self._select_scavenge_gun(True), enabled=(self.guns > 0))

            # Confirm button
            can_confirm = (self.selected_risk is not None) and (self.selected_give_gun is not None)
            add4("CONFIRM SCAVENGE", self._confirm_scavenge, enabled=can_confirm, width=280)

    def _select_scavenge_risk(self, r):
        self.selected_risk = r
        self.popup.show(f"Scavenge plan: {r}. Choose armament.", 1.6)

    def _select_scavenge_gun(self, give):
        self.selected_give_gun = give
        if give:
            self.popup.show("Sending them with a gun.", 1.4)
        else:
            self.popup.show("Sending them unarmed.", 1.4)

    def _confirm_scavenge(self):
        if self.selected_risk is None or self.selected_give_gun is None:
            return
        self.do_scavenge(self.selected_risk, self.selected_give_gun)

    def current_background(self):
        if self.view == VIEW_DRIVER_INSIDE:
            return self.bg_driver_inside
        if self.view == VIEW_ENGINE:
            return self.bg_engine
        if self.view == VIEW_CREW:
            return self.bg_crew
        if self.view == VIEW_AMMO:
            return self.bg_ammo
        if self.view == VIEW_OUT_DRIVER:
            return self.bg_out_driver
        if self.view == VIEW_OUT_LEFT:
            return self.bg_out_left
        if self.view == VIEW_OUT_RIGHT:
            return self.bg_out_right
        return self.bg_driver_inside

    def update_driving(self, dt):
        if not self.driving or self.level_active:
            return

        # Fuel consumption
        self.fuel_accum += FUEL_CONSUMED_PER_SEC * dt
        while self.fuel_accum >= 1.0:
            self.fuel -= 1
            self.fuel_accum -= 1.0
            if self.fuel <= 0:
                self.fuel = 0
                self.begin_level("fuel")
                return

        # Random breakdown timer
        self.breakdown_timer -= dt
        if self.breakdown_timer <= 0:
            self.begin_level("breakdown")

    def draw_hud(self):
        # Top-left stats box
        pad = 10
        lines = [
            f"Fuel: {self.fuel}",
            f"Parts: {self.parts}",
            f"Shells: {self.shells}",
            f"Guns: {self.guns}",
            f"Crew: {self.crew}",
        ]
        if self.level_active:
            lines.append(f"Zombies Alive: {self.total_zombies_alive()}")
            if self.engine_broken:
                lines.append("Engine: BROKEN")
            else:
                lines.append("Engine: READY")

        box_w = 260
        box_h = pad * 2 + len(lines) * 22
        box = pygame.Rect(12, 12, box_w, box_h)
        pygame.draw.rect(self.screen, (0, 0, 0), box, border_radius=10)
        pygame.draw.rect(self.screen, (140, 140, 140), box, width=2, border_radius=10)

        y = box.y + pad
        for s in lines:
            t = self.font.render(s, True, (255, 255, 255))
            self.screen.blit(t, (box.x + pad, y))
            y += 22

        # Driving banner
        if self.driving and not self.level_active and not self.game_over:
            t = self.bigfont.render("DRIVING", True, (255, 255, 255))
            self.screen.blit(t, t.get_rect(midtop=(SCREEN_W // 2, 10)))
        elif self.level_active and not self.game_over:
            t = self.bigfont.render("BROKEN DOWN (LEVEL)", True, (255, 220, 220))
            self.screen.blit(t, t.get_rect(midtop=(SCREEN_W // 2, 10)))

        if self.scavenge_mode:
            info = "SCAVENGE: Choose risk, then gun, then confirm"
            t2 = self.font.render(info, True, (255, 255, 120))
            self.screen.blit(t2, (12, 12 + 140))

    def draw_outside_content(self):
        """If looking outside during a level, draw items and zombies for that view."""
        if self.view not in OUTSIDE_VIEWS:
            return

        # If driving: outside view is just monotony - no sprites shown.
        if not self.level_active:
            # Optional subtle text overlay
            txt = self.font.render("No man's land slides past... nothing to report.", True, (230, 230, 230))
            r = txt.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2))
            self.screen.blit(txt, r)
            return

        # Items
        for it in self.level_items.get(self.view, []):
            if not it.collected:
                self.screen.blit(it.sprite, it.rect)

        # Zombies
        for z in self.level_zombies.get(self.view, []):
            if z.alive:
                self.screen.blit(z.sprite, z.rect)

        # Instruction hint
        hint = "Click fuel/parts/shells to collect. Click zombies to shoot (gunner views)."
        t = self.font.render(hint, True, (240, 240, 240))
        self.screen.blit(t, (12, SCREEN_H - 250))

    def handle_outside_click(self, pos):
        """Priority: zombies (if gunner view), otherwise items."""
        if self.view == VIEW_OUT_LEFT or self.view == VIEW_OUT_RIGHT:
            # gunner views: shooting zombies is the main interaction
            # but allow clicking items too if not on a zombie
            if self.level_active:
                # if clicked a zombie, it will consume shells + kill; else try item
                zombies = self.level_zombies.get(self.view, [])
                for z in zombies:
                    if z.alive and z.rect.collidepoint(pos):
                        self.handle_shot_click(pos)
                        return
                self.handle_item_click(pos)
            else:
                self.popup.show("The monotonous grey scenery of no man's land slips past. Nothing to report.", 2.0)
        else:
            # driver outside view: collect items (and you can also shoot? but you didn't ask for it)
            self.handle_item_click(pos)

    def update_fade(self):
        if not self.fading:
            return

        if self.fade_phase == "out":
            self.fade_alpha += FADE_SPEED
            if self.fade_alpha >= 255:
                self.fade_alpha = 255
                # swap view at full black
                if self.pending_view is not None:
                    self.view = self.pending_view
                self.fade_phase = "in"
        else:
            self.fade_alpha -= FADE_SPEED
            if self.fade_alpha <= 0:
                self.fade_alpha = 0
                self.fading = False
                self.pending_view = None

    def draw_fade_overlay(self):
        if not self.fading:
            return
        overlay = pygame.Surface((SCREEN_W, SCREEN_H)).convert()
        overlay.fill((0, 0, 0))
        overlay.set_alpha(self.fade_alpha)
        self.screen.blit(overlay, (0, 0))

    def main_loop(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            # Update
            self.popup.update(dt)
            if not self.game_over:
                self.update_driving(dt)

            self.update_fade()
            self.build_ui()

            # Events
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.running = False

                if self.game_over:
                    if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                        self.running = False
                    continue

                # Buttons
                for b in self.buttons:
                    b.handle_event(e)

                # Outside interactions
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    # ignore clicks on UI area (bottom strip)
                    if e.pos[1] < SCREEN_H - 230:  # allow some UI above, but keep simple
                        if self.view in OUTSIDE_VIEWS:
                            self.handle_outside_click(e.pos)

            # Draw
            self.screen.blit(self.current_background(), (0, 0))
            self.draw_outside_content()
            self.draw_hud()

            # Buttons on top
            for b in self.buttons:
                b.draw(self.screen)

            # Popup and fade
            self.popup.draw(self.screen, self.font)
            self.draw_fade_overlay()

            # Game over overlay
            if self.game_over:
                overlay = pygame.Surface((SCREEN_W, SCREEN_H)).convert()
                overlay.fill((0, 0, 0))
                overlay.set_alpha(160)
                self.screen.blit(overlay, (0, 0))
                t1 = self.bigfont.render("GAME OVER", True, (255, 255, 255))
                t2 = self.font.render("Press ESC to quit.", True, (220, 220, 220))
                self.screen.blit(t1, t1.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 - 20)))
                self.screen.blit(t2, t2.get_rect(center=(SCREEN_W // 2, SCREEN_H // 2 + 30)))

            pygame.display.flip()

        pygame.quit()

# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":
    # Create assets folder hint
    if not os.path.exists(ASSET_DIR):
        os.makedirs(ASSET_DIR, exist_ok=True)
        print(f"Created '{ASSET_DIR}/' folder. Drop your png files there to replace placeholders.")

    game = Game()
    game.main_loop()
