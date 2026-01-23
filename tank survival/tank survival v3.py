"""
Never-ending single-player Tkinter tank survival game (prototype)
- Pseudo-3D via static PNG "views" (internal + outside vision slits)
- Level loop: driving -> breakdown/out-of-fuel -> scavenging/fixing/refueling -> start driving again
- Outside scenes get randomly populated with items + zombies each level
- Click zombies (in gunner outside views) to fire cannon and kill them (costs shells)
- Fade transitions between views: fade-to-black, then fade-in

Dependencies:
    pip install pillow

Put your PNGs in the same folder as this script (or change the paths below).
If a PNG is missing, the game generates a placeholder image automatically.
"""

import os
import random
import time
import tkinter as tk
from tkinter import messagebox
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageTk


# =========================
# TUNABLE GAME VARIABLES
# =========================
STARTING_FUEL = 200            # starting fuel units
FUEL_CONSUMPTION_PER_SEC = 1   # fuel units drained per second while driving

STARTING_SHELLS = 6            # starting shells
STARTING_GUNS = 4              # starting guns
STARTING_CREW = 4              # starting crew

BREAKDOWN_MIN_SEC = 30         # random breakdown window
BREAKDOWN_MAX_SEC = 180

# Scavenge returns fuel between these, per fuel can found (subject to change)
FUEL_CAN_MIN = 10
FUEL_CAN_MAX = 100

# Scavenge risk tuning
ZOMBIE_PENALTY_PER_ZOMBIE = 0.05
GUN_BONUS = 0.15
CHANCE_MIN = 0.05
CHANCE_MAX = 0.95

# Fade tuning
FADE_STEPS = 14
FADE_DELAY_MS = 25

# Canvas sizing (match your placeholder images if you want)
VIEW_W = 1200
VIEW_H = 800

# =========================
# VIEW IMAGE PATHS
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Four internal PNGs
INTERNAL_VIEW_PATHS = {
    "ENGINE": os.path.join(BASE_DIR, "engine.png"),
    "DRIVER": os.path.join(BASE_DIR, "driver.png"),
    "LEFT_GUNNER": os.path.join(BASE_DIR, "left.png"),
    "RIGHT_GUNNER": os.path.join(BASE_DIR, "right.png"),
}

OUTSIDE_VIEW_PATHS = {
    "OUT_DRIVER": os.path.join(BASE_DIR, "outdriver.png"),
    "OUT_LEFT": os.path.join(BASE_DIR, "outleft.png"),
    "OUT_RIGHT": os.path.join(BASE_DIR, "outright.png"),
}



# =========================
# DATA STRUCTURES
# =========================
@dataclass
class Sprite:
    kind: str  # "fuel", "part", "shell", "zombie"
    x: int
    y: int
    w: int
    h: int
    canvas_id: Optional[int] = None
    # For zombies we can track alive, but removing canvas_id is enough.


@dataclass
class LevelState:
    active: bool = False
    reason: str = ""
    # "scavengeable items" count (for the level)
    fuel_cans: int = 0
    parts: int = 0
    shells: int = 0
    zombies: int = 0


# =========================
# MAIN APP
# =========================
class TankGame(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MkV Tank Survival (Prototype)")
        self.geometry("1100x650")
        self.minsize(1000, 620)

        # Game resources
        self.fuel = STARTING_FUEL
        self.parts = 0
        self.shells = STARTING_SHELLS
        self.guns = STARTING_GUNS
        self.crew = STARTING_CREW

        # Drive/level state
        self.driving = True
        self.engine_broken = False  # True during a level where engine broke
        self.out_of_fuel = False    # True during a level where fuel hit 0
        self.level = LevelState(active=False)

        # Views
        self.current_view_key = "DRIVER"  # start internal driver view

        # Sprite stuff (per outside view)
        self.sprites_by_view: Dict[str, List[Sprite]] = {
            "OUT_DRIVER": [],
            "OUT_LEFT": [],
            "OUT_RIGHT": [],
        }

        # Image cache
        self._pil_cache: Dict[str, Image.Image] = {}
        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._fade_work_img: Optional[ImageTk.PhotoImage] = None

        # UI layout
        self._build_ui()

        # Load initial view
        self._show_view(self.current_view_key, do_fade=False)

        # Timers
        self._fuel_tick_after_id: Optional[str] = None
        self._breakdown_after_id: Optional[str] = None

        # Start driving loop + schedule breakdown
        self._start_timers_for_driving()

    # -------------------------
    # UI
    # -------------------------
    def _build_ui(self):
        root = tk.Frame(self, padx=10, pady=10)
        root.pack(fill="both", expand=True)

        # Left sidebar controls
        sidebar = tk.Frame(root, width=250)
        sidebar.pack(side="left", fill="y")

        # Main view
        main = tk.Frame(root)
        main.pack(side="right", fill="both", expand=True)

        # Status bar
        self.status_var = tk.StringVar()
        self.status_label = tk.Label(
            sidebar, textvariable=self.status_var, justify="left",
            font=("Segoe UI", 10), anchor="w"
        )
        self.status_label.pack(fill="x", pady=(0, 10))
        self._update_status()

        # View buttons (internal)
        tk.Label(sidebar, text="Internal Views", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Button(sidebar, text="Engine View", command=lambda: self._transition_to("ENGINE")).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Driver View", command=lambda: self._transition_to("DRIVER")).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Left Gunner View", command=lambda: self._transition_to("LEFT_GUNNER")).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Right Gunner View", command=lambda: self._transition_to("RIGHT_GUNNER")).pack(fill="x", pady=2)

        tk.Label(sidebar, text=" ", font=("Segoe UI", 3)).pack()

        # Outside (vision slits)
        tk.Label(sidebar, text="Look Outside (Vision Slits)", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Button(sidebar, text="Driver Vision Slit", command=lambda: self._attempt_outside("OUT_DRIVER")).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Left Gunner Slit", command=lambda: self._attempt_outside("OUT_LEFT")).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Right Gunner Slit", command=lambda: self._attempt_outside("OUT_RIGHT")).pack(fill="x", pady=2)

        tk.Label(sidebar, text=" ", font=("Segoe UI", 3)).pack()

        # Driver controls
        tk.Label(sidebar, text="Driver Controls", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Button(sidebar, text="STOP (Triggers new level)", command=self._driver_stop).pack(fill="x", pady=2)
        tk.Button(sidebar, text="START (After repairs/refuel)", command=self._driver_start).pack(fill="x", pady=2)

        tk.Label(sidebar, text=" ", font=("Segoe UI", 3)).pack()

        # Engine controls
        tk.Label(sidebar, text="Engine / Actions", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Button(sidebar, text="Fix Engine (cost: 1 part)", command=self._fix_engine).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Send Scavenger", command=self._open_scavenge_dialog).pack(fill="x", pady=2)

        # Canvas for view rendering
        self.canvas = tk.Canvas(main, width=VIEW_W, height=VIEW_H, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Bind clicks for zombie shooting
        self.canvas.bind("<Button-1>", self._on_canvas_click)

    # -------------------------
    # Status / Utility
    # -------------------------
    def _update_status(self):
        state = "DRIVING" if self.driving else "STOPPED (LEVEL ACTIVE)"
        level_info = ""
        if self.level.active:
            level_info = (
                f"\nLevel reason: {self.level.reason}"
                f"\nOutside spawns: fuel_cans={self.level.fuel_cans}, parts={self.level.parts}, shells={self.level.shells}, zombies={self.level.zombies}"
            )
        self.status_var.set(
            f"STATE: {state}"
            f"\nFuel: {self.fuel}"
            f"\nParts: {self.parts}"
            f"\nShells: {self.shells}"
            f"\nGuns: {self.guns}"
            f"\nCrew: {self.crew}"
            f"{level_info}"
        )

    def _clamp(self, x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    # -------------------------
    # Image loading / placeholders
    # -------------------------
    def _load_or_make_placeholder(self, path: str, label: str) -> Image.Image:
        # Cache by path
        if path in self._pil_cache:
            return self._pil_cache[path]

        if os.path.exists(path):
            img = Image.open(path).convert("RGBA")
            img = img.resize((VIEW_W, VIEW_H), Image.LANCZOS)
            self._pil_cache[path] = img
            return img

        # Placeholder image
        img = Image.new("RGBA", (VIEW_W, VIEW_H), (40, 40, 40, 255))
        draw = ImageDraw.Draw(img)

        # Simple framing
        draw.rectangle([20, 20, VIEW_W - 20, VIEW_H - 20], outline=(120, 120, 120, 255), width=4)
        draw.text((40, 40), "MISSING IMAGE", fill=(220, 220, 220, 255))
        draw.text((40, 80), f"{label}", fill=(220, 220, 220, 255))
        draw.text((40, 120), f"Expected file: {path}", fill=(180, 180, 180, 255))

        self._pil_cache[path] = img
        return img

    def _get_view_base_image(self, view_key: str) -> Image.Image:
        if view_key in INTERNAL_VIEW_PATHS:
            return self._load_or_make_placeholder(INTERNAL_VIEW_PATHS[view_key], f"INTERNAL VIEW: {view_key}")
        if view_key in OUTSIDE_VIEW_PATHS:
            return self._load_or_make_placeholder(OUTSIDE_VIEW_PATHS[view_key], f"OUTSIDE VIEW: {view_key}")
        return self._load_or_make_placeholder("missing.png", f"UNKNOWN VIEW: {view_key}")

    # -------------------------
    # View transitions
    # -------------------------
    def _transition_to(self, view_key: str):
        # Internal view transitions always allowed
        self._show_view(view_key, do_fade=True)

    def _attempt_outside(self, outside_key: str):
        # While driving, outside is "monotonous grey scenery" popup (per your spec)
        if self.driving:
            messagebox.showinfo(
                "Nothing to report",
                "The monotonous grey scenery of no man's land slips past. Nothing to report."
            )
            return
        self._show_view(outside_key, do_fade=True)

    def _show_view(self, view_key: str, do_fade: bool = True):
        prev = self.current_view_key
        self.current_view_key = view_key

        # Clear canvas items (including sprites) and redraw
        if not do_fade:
            self._draw_view_instant(view_key)
            return

        # Fade: current -> black -> target
        prev_img = self._render_composited_image(prev)
        next_img = self._render_composited_image(view_key)
        self._fade_transition(prev_img, next_img)

    def _draw_view_instant(self, view_key: str):
        img = self._render_composited_image(view_key)
        self._tk_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)

        # If outside view and level active, draw sprites as canvas rectangles (clickable by coord)
        self._draw_sprites_for_current_view()

    def _fade_transition(self, from_img: Image.Image, to_img: Image.Image):
        # Step A: fade to black
        black = Image.new("RGBA", (VIEW_W, VIEW_H), (0, 0, 0, 255))

        def do_step_fade_to_black(i: int):
            if i > FADE_STEPS:
                # Step B: fade in to target
                do_step_fade_from_black(0)
                return
            t = i / FADE_STEPS
            blended = Image.blend(from_img, black, t)
            self._fade_work_img = ImageTk.PhotoImage(blended)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self._fade_work_img)
            self.after(FADE_DELAY_MS, lambda: do_step_fade_to_black(i + 1))

        def do_step_fade_from_black(i: int):
            if i > FADE_STEPS:
                # Finalize to target, then draw sprites
                self._tk_img = ImageTk.PhotoImage(to_img)
                self.canvas.delete("all")
                self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)
                self._draw_sprites_for_current_view()
                return
            t = i / FADE_STEPS
            blended = Image.blend(black, to_img, t)
            self._fade_work_img = ImageTk.PhotoImage(blended)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self._fade_work_img)
            self.after(FADE_DELAY_MS, lambda: do_step_fade_from_black(i + 1))

        do_step_fade_to_black(0)

    # -------------------------
    # Compositing base image + HUD text (and optionally bake sprites)
    # -------------------------
    def _render_composited_image(self, view_key: str) -> Image.Image:
        base = self._get_view_base_image(view_key).copy()
        draw = ImageDraw.Draw(base)

        # Minimal overlay text so you always know where you are
        draw.rectangle([0, 0, VIEW_W, 30], fill=(0, 0, 0, 160))
        draw.text((10, 7), f"VIEW: {view_key}", fill=(255, 255, 255, 255))

        # If outside view and level active, hint click-to-shoot (for gunner outside views)
        if view_key in ("OUT_LEFT", "OUT_RIGHT") and self.level.active:
            draw.text((200, 7), "Click zombies to fire cannon (costs 1 shell).", fill=(220, 220, 220, 255))

        if view_key == "ENGINE":
            if self.level.active:
                msg = "ENGINE STATUS: BROKEN / STOPPED"
            else:
                msg = "ENGINE STATUS: RUNNING"
            draw.text((10, 40), msg, fill=(255, 255, 255, 255))

        return base

    # -------------------------
    # Driving / Level timers
    # -------------------------
    def _start_timers_for_driving(self):
        self._cancel_timers()

        self.driving = True
        self.level.active = False
        self.engine_broken = False
        self.out_of_fuel = False

        self._update_status()

        # Fuel tick
        self._fuel_tick_after_id = self.after(1000, self._fuel_tick)

        # Breakdown scheduling
        delay = random.randint(BREAKDOWN_MIN_SEC, BREAKDOWN_MAX_SEC) * 1000
        self._breakdown_after_id = self.after(delay, self._trigger_breakdown_level)

    def _cancel_timers(self):
        if self._fuel_tick_after_id is not None:
            try:
                self.after_cancel(self._fuel_tick_after_id)
            except Exception:
                pass
            self._fuel_tick_after_id = None

        if self._breakdown_after_id is not None:
            try:
                self.after_cancel(self._breakdown_after_id)
            except Exception:
                pass
            self._breakdown_after_id = None

    def _fuel_tick(self):
        if not self.driving:
            return
        self.fuel -= FUEL_CONSUMPTION_PER_SEC
        if self.fuel <= 0:
            self.fuel = 0
            self._trigger_out_of_fuel_level()
            return
        self._update_status()
        self._fuel_tick_after_id = self.after(1000, self._fuel_tick)

    # -------------------------
    # Starting/Stopping Driving
    # -------------------------
    def _driver_stop(self):
        # Per spec: stopping triggers a new level immediately.
        if not self.driving:
            return
        self._trigger_manual_stop_level()

    def _driver_start(self):
        # Only possible if we're stopped and requirements met:
        # - if breakdown: must have fixed engine (engine_broken must be False)
        # - if out_of_fuel: must have fuel > 0
        if self.driving:
            return

        if self.engine_broken:
            messagebox.showinfo("Cannot start", "The engine is broken. Fix it first (Engine View -> Fix Engine).")
            return

        if self.out_of_fuel and self.fuel <= 0:
            messagebox.showinfo("Cannot start", "No fuel. You need to scavenge fuel before starting.")
            return

        # Start driving ends level
        self._start_timers_for_driving()
        # (Optional) go back to internal driver view
        self._show_view("DRIVER", do_fade=True)

    # -------------------------
    # Level creation
    # -------------------------
    def _trigger_breakdown_level(self):
        if not self.driving:
            return
        self._start_level(reason="Engine breakdown")

    def _trigger_out_of_fuel_level(self):
        if not self.driving:
            return
        self._start_level(reason="Out of fuel")

    def _trigger_manual_stop_level(self):
        if not self.driving:
            return
        self._start_level(reason="Manual stop")

    def _start_level(self, reason: str):
        self._cancel_timers()
        self.driving = False
        self.level.active = True
        self.level.reason = reason

        # Flags that determine what must be done before starting
        self.engine_broken = (reason == "Engine breakdown")
        self.out_of_fuel = (reason == "Out of fuel")


        # Populate no man's land spawns (guarantee at least one part per your spec)
        # You can tune these ranges later.
        self.level.parts = max(1, random.randint(1, 3))
        self.level.fuel_cans = random.randint(0, 3)
        self.level.shells = random.randint(0, 3)
        self.level.zombies = random.randint(0, 6)

        # Build sprites for outside views
        self._populate_outside_sprites()

        self._update_status()

        # If currently looking outside, redraw sprites; otherwise leave view alone
        self._draw_view_instant(self.current_view_key)

    def _populate_outside_sprites(self):
        # Clear existing
        for k in self.sprites_by_view:
            self.sprites_by_view[k].clear()

        # Helper: place N sprites randomly
        def place(kind: str, n: int):
            for _ in range(n):
                x = random.randint(80, VIEW_W - 120)
                y = random.randint(90, VIEW_H - 100)
                w = 50
                h = 50
                view_key = random.choice(["OUT_DRIVER", "OUT_LEFT", "OUT_RIGHT"])
                self.sprites_by_view[view_key].append(Sprite(kind=kind, x=x, y=y, w=w, h=h))

        place("part", self.level.parts)
        place("fuel", self.level.fuel_cans)
        place("shell", self.level.shells)
        place("zombie", self.level.zombies)

    # -------------------------
    # Drawing sprites (simple rectangles + labels)
    # -------------------------
    def _draw_sprites_for_current_view(self):
        # Only draw sprite overlays in outside views and only while level is active
        if not self.level.active:
            return
        if self.current_view_key not in ("OUT_DRIVER", "OUT_LEFT", "OUT_RIGHT"):
            return

        # Draw them on top of current background image
        sprites = self.sprites_by_view[self.current_view_key]
        for sp in sprites:
            # Color coding
            if sp.kind == "fuel":
                fill = "#2b8a3e"
                txt = "FUEL"
            elif sp.kind == "part":
                fill = "#6c757d"
                txt = "PART"
            elif sp.kind == "shell":
                fill = "#a61e4d"
                txt = "SHELL"
            else:
                fill = "#c92a2a"
                txt = "ZOMBIE"

            sp.canvas_id = self.canvas.create_rectangle(sp.x, sp.y, sp.x + sp.w, sp.y + sp.h, fill=fill, outline="black", width=2)
            self.canvas.create_text(sp.x + sp.w // 2, sp.y + sp.h // 2, text=txt, fill="white", font=("Segoe UI", 9, "bold"))

    # -------------------------
    # Clicking: shoot zombie (gunner outside views)
    # -------------------------
    def _on_canvas_click(self, event):
        if not self.level.active:
            return
        if self.current_view_key not in ("OUT_LEFT", "OUT_RIGHT"):
            return  # only gunner outside views can shoot, per your description

        sprites = self.sprites_by_view[self.current_view_key]
        # Find topmost zombie under cursor
        clicked_idx = None
        for i in range(len(sprites) - 1, -1, -1):
            sp = sprites[i]
            if sp.kind != "zombie":
                continue
            if sp.x <= event.x <= sp.x + sp.w and sp.y <= event.y <= sp.y + sp.h:
                clicked_idx = i
                break

        if clicked_idx is None:
            return

        if self.shells <= 0:
            messagebox.showinfo("No shells", "You have no shells left to fire the cannon.")
            return

        # Fire!
        self.shells -= 1
        # Remove zombie sprite
        del sprites[clicked_idx]
        # Redraw view (simple approach: re-render background then sprites)
        self._draw_view_instant(self.current_view_key)
        self._update_status()

    # -------------------------
    # Engine repair
    # -------------------------
    def _fix_engine(self):
        if not self.level.active:
            messagebox.showinfo("No repair needed", "The tank is currently driving; the engine isn't in a stopped level.")
            return

        if not self.engine_broken:
            messagebox.showinfo("No repair needed", "The engine isn't broken.")
            return

        if self.parts <= 0:
            messagebox.showinfo("Not enough parts", "You do not have enough parts to fix the engine.")
            return

        self.parts -= 1
        self.engine_broken = False
        messagebox.showinfo("Engine fixed", "You patch the engine with scavenged parts. It should run again.")
        self._update_status()
        # Refresh engine view overlay if currently on it
        if self.current_view_key == "ENGINE":
            self._draw_view_instant("ENGINE")

    # -------------------------
    # Scavenging
    # -------------------------
    def _open_scavenge_dialog(self):
        if not self.level.active:
            messagebox.showinfo("Cannot scavenge", "You can only scavenge while stopped in a level.")
            return
        if self.crew <= 0:
            messagebox.showinfo("No crew", "You have no crew left to send.")
            return

        dlg = tk.Toplevel(self)
        dlg.title("Send Scavenger")
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="Choose scavenging approach:", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))

        approach = tk.StringVar(value="quick")
        tk.Radiobutton(dlg, text="Quick (up to 1/3 items, 75% base return)", variable=approach, value="quick").pack(anchor="w", padx=10)
        tk.Radiobutton(dlg, text="Moderate (up to 50% items, 50% base return)", variable=approach, value="moderate").pack(anchor="w", padx=10)
        tk.Radiobutton(dlg, text="Greedy (up to 100% items, 33% base return)", variable=approach, value="greedy").pack(anchor="w", padx=10)

        give_gun = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text="Give scavenger a gun (increases survival chance; lost if they die)", variable=give_gun).pack(anchor="w", padx=10, pady=(8, 0))

        tk.Label(dlg, text="Note: more zombies reduces survival chance.", fg="#cccccc").pack(anchor="w", padx=10, pady=(6, 0))

        btn_row = tk.Frame(dlg)
        btn_row.pack(fill="x", padx=10, pady=10)

        tk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side="right")
        tk.Button(btn_row, text="Send", command=lambda: self._resolve_scavenge(dlg, approach.get(), give_gun.get())).pack(side="right", padx=(0, 8))

    def _resolve_scavenge(self, dlg: tk.Toplevel, approach: str, give_gun: bool):
        dlg.destroy()

        # Determine base chance and max fraction of items retrieved
        if approach == "quick":
            base = 0.75
            max_frac = 1/3
        elif approach == "moderate":
            base = 0.50
            max_frac = 0.50
        else:
            base = 0.33
            max_frac = 1.00

        # Apply modifiers
        chance = base
        chance -= self.level.zombies * ZOMBIE_PENALTY_PER_ZOMBIE
        if give_gun and self.guns > 0:
            chance += GUN_BONUS
        chance = self._clamp(chance, CHANCE_MIN, CHANCE_MAX)

        # If giving a gun, remove it now; it returns only if the scavenger survives
        gun_committed = False
        if give_gun and self.guns > 0:
            self.guns -= 1
            gun_committed = True

        # "Scavenging..." effect (resolve after a short delay)
        self._update_status()
        messagebox.showinfo("Scavenging", "A crew member climbs out into no man's land to scavenge...")

        survived = (random.random() < chance)

        if not survived:
            self.crew -= 1
            # Gun is lost if committed
            messagebox.showwarning(
                "Lost",
                "The scavenger does not return.\n"
                "A shape vanishes into the haze and does not come back."
            )
            self._update_status()
            if self.crew <= 0:
                messagebox.showerror("Game Over", "All crew are dead. The tank falls silent.")
                self.destroy()
            return

        # Survived: if gun was committed, it returns
        if gun_committed:
            self.guns += 1

        # Retrieve items from what remains on the map (by fraction, random up to max_frac)
        frac = random.random() * max_frac

        # Compute totals available remaining in all outside views
        avail = self._count_remaining_items()

        got_parts = int(avail["part"] * frac)
        got_shells = int(avail["shell"] * frac)
        got_fuel_cans = int(avail["fuel"] * frac)

        # Always possible to get at least *something* if anything exists; nudge small
        if (got_parts + got_shells + got_fuel_cans) == 0 and (avail["part"] + avail["shell"] + avail["fuel"]) > 0:
            # Pick one type that exists
            choices = []
            if avail["part"] > 0: choices.append("part")
            if avail["shell"] > 0: choices.append("shell")
            if avail["fuel"] > 0: choices.append("fuel")
            pick = random.choice(choices)
            if pick == "part":
                got_parts = 1
            elif pick == "shell":
                got_shells = 1
            else:
                got_fuel_cans = 1

        # Convert fuel cans -> actual fuel
        fuel_gained = 0
        for _ in range(got_fuel_cans):
            fuel_gained += random.randint(FUEL_CAN_MIN, FUEL_CAN_MAX)

        # Apply gains
        self.parts += got_parts
        self.shells += got_shells
        self.fuel += fuel_gained

        # Remove collected items from the map (so repeated scavenging matters)
        self._remove_items_from_map("part", got_parts)
        self._remove_items_from_map("shell", got_shells)
        self._remove_items_from_map("fuel", got_fuel_cans)

        self._update_status()
        self._draw_view_instant(self.current_view_key)

        messagebox.showinfo(
            "Returned",
            "The scavenger returns, mud-streaked and breathing hard.\n\n"
            f"Gains:\n"
            f"  Parts: +{got_parts}\n"
            f"  Shells: +{got_shells}\n"
            f"  Fuel: +{fuel_gained}\n\n"
            f"Survival chance was: {int(chance*100)}%"
        )

    def _count_remaining_items(self) -> Dict[str, int]:
        counts = {"fuel": 0, "part": 0, "shell": 0, "zombie": 0}
        for view_key, sprites in self.sprites_by_view.items():
            for sp in sprites:
                if sp.kind in counts:
                    counts[sp.kind] += 1
        return counts

    def _remove_items_from_map(self, kind: str, n: int):
        # Remove n items of given kind across all outside views
        remaining = n
        for view_key in ("OUT_DRIVER", "OUT_LEFT", "OUT_RIGHT"):
            if remaining <= 0:
                break
            sprites = self.sprites_by_view[view_key]
            i = 0
            while i < len(sprites) and remaining > 0:
                if sprites[i].kind == kind:
                    del sprites[i]
                    remaining -= 1
                else:
                    i += 1

    # -------------------------
    # Run
    # -------------------------
    def run(self):
        self.mainloop()


if __name__ == "__main__":
    TankGame().run()
