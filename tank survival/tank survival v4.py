"""
Never-ending single-player Tkinter tank survival game (prototype)
Now with:
- Ammo boxes (ammo.png) that give 100 ammo when scavenged
- Machine gun fire: right-click zombies in gunner outside views (costs 33 ammo)
- 0–2 ammo boxes spawn randomly each level

Dependencies:
    pip install pillow
"""

import os
import random
import tkinter as tk
from tkinter import messagebox
from dataclasses import dataclass
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageTk


# =========================
# PATH BASE (so images work no matter where you launch from)
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# =========================
# TUNABLE GAME VARIABLES
# =========================
STARTING_FUEL = 200             # starting fuel units
FUEL_CONSUMPTION_PER_SEC = 1    # fuel units drained per second while driving

STARTING_SHELLS = 6             # starting shells (cannon)
STARTING_GUNS = 4               # starting guns
STARTING_CREW = 4               # starting crew
STARTING_AMMO = 200             # starting machine-gun ammo

BREAKDOWN_MIN_SEC = 30          # random breakdown window
BREAKDOWN_MAX_SEC = 180

# Fuel can yields
FUEL_CAN_MIN = 10
FUEL_CAN_MAX = 100

# Ammo box yield
AMMO_PER_BOX = 100
MG_AMMO_COST = 33               # ammo cost per machine-gun burst

# Scavenge risk tuning
ZOMBIE_PENALTY_PER_ZOMBIE = 0.05
GUN_BONUS = 0.15
CHANCE_MIN = 0.05
CHANCE_MAX = 0.95

# Fade tuning
FADE_STEPS = 14
FADE_DELAY_MS = 25

# Canvas sizing (match your images)
VIEW_W = 1200
VIEW_H = 800


# =========================
# VIEW IMAGE PATHS
# =========================
# Four internal PNGs
INTERNAL_VIEW_PATHS = {
    "ENGINE": os.path.join(BASE_DIR, "engine.png"),
    "DRIVER": os.path.join(BASE_DIR, "driver.png"),
    "LEFT_GUNNER": os.path.join(BASE_DIR, "left.png"),
    "RIGHT_GUNNER": os.path.join(BASE_DIR, "right.png"),
}

# Three outside PNGs (vision slit scenes)
OUTSIDE_VIEW_PATHS = {
    "OUT_DRIVER": os.path.join(BASE_DIR, "outdriver.png"),
    "OUT_LEFT": os.path.join(BASE_DIR, "outleft.png"),
    "OUT_RIGHT": os.path.join(BASE_DIR, "outright.png"),
}

# Ammo sprite image
AMMO_SPRITE_PATH = os.path.join(BASE_DIR, "ammo.png")


# =========================
# DATA STRUCTURES
# =========================
@dataclass
class Sprite:
    kind: str  # "fuel", "part", "shell", "zombie", "ammo"
    x: int
    y: int
    w: int
    h: int
    canvas_id: Optional[int] = None


@dataclass
class LevelState:
    active: bool = False
    reason: str = ""
    # scavengeable items remaining
    fuel_cans: int = 0
    parts: int = 0
    shells: int = 0
    zombies: int = 0
    ammo_boxes: int = 0


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
        self.ammo = STARTING_AMMO

        # Drive/level state
        self.driving = True
        self.engine_broken = False
        self.out_of_fuel = False
        self.level = LevelState(active=False)

        # Views
        self.current_view_key = "DRIVER"

        # Sprite data (per outside view)
        self.sprites_by_view: Dict[str, List[Sprite]] = {
            "OUT_DRIVER": [],
            "OUT_LEFT": [],
            "OUT_RIGHT": [],
        }

        # Image caches
        self._pil_cache: Dict[str, Image.Image] = {}
        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._fade_work_img: Optional[ImageTk.PhotoImage] = None
        self._sprite_icons: Dict[str, ImageTk.PhotoImage] = {}

        # UI
        self._build_ui()
        self._show_view(self.current_view_key, do_fade=False)

        # Timers
        self._fuel_tick_after_id: Optional[str] = None
        self._breakdown_after_id: Optional[str] = None

        self._start_timers_for_driving()

    # -------------------------
    # UI
    # -------------------------
    def _build_ui(self):
        root = tk.Frame(self, padx=10, pady=10)
        root.pack(fill="both", expand=True)

        sidebar = tk.Frame(root, width=250)
        sidebar.pack(side="left", fill="y")

        main = tk.Frame(root)
        main.pack(side="right", fill="both", expand=True)

        # Status
        self.status_var = tk.StringVar()
        self.status_label = tk.Label(
            sidebar, textvariable=self.status_var, justify="left",
            font=("Segoe UI", 10), anchor="w"
        )
        self.status_label.pack(fill="x", pady=(0, 10))
        self._update_status()

        # Internal views
        tk.Label(sidebar, text="Internal Views", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Button(sidebar, text="Engine View", command=lambda: self._transition_to("ENGINE")).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Driver View", command=lambda: self._transition_to("DRIVER")).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Left Gunner View", command=lambda: self._transition_to("LEFT_GUNNER")).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Right Gunner View", command=lambda: self._transition_to("RIGHT_GUNNER")).pack(fill="x", pady=2)

        tk.Label(sidebar, text=" ", font=("Segoe UI", 3)).pack()

        # Outside views
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

        # Engine / Actions
        tk.Label(sidebar, text="Engine / Actions", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Button(sidebar, text="Fix Engine (cost: 1 part)", command=self._fix_engine).pack(fill="x", pady=2)
        tk.Button(sidebar, text="Send Scavenger", command=self._open_scavenge_dialog).pack(fill="x", pady=2)

        # Main canvas
        self.canvas = tk.Canvas(main, width=VIEW_W, height=VIEW_H, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Bind clicks: left = cannon, right = machine gun
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Button-3>", self._on_canvas_click)

    # -------------------------
    # Status & utils
    # -------------------------
    def _update_status(self):
        state = "DRIVING" if self.driving else "STOPPED (LEVEL ACTIVE)"
        level_info = ""
        if self.level.active:
            level_info = (
                f"\nLevel reason: {self.level.reason}"
                f"\nOutside spawns: fuel_cans={self.level.fuel_cans}, parts={self.level.parts}, "
                f"shells={self.level.shells}, ammo_boxes={self.level.ammo_boxes}, zombies={self.level.zombies}"
            )

        self.status_var.set(
            f"STATE: {state}"
            f"\nFuel: {self.fuel}"
            f"\nParts: {self.parts}"
            f"\nShells: {self.shells}"
            f"\nAmmo: {self.ammo}"
            f"\nGuns: {self.guns}"
            f"\nCrew: {self.crew}"
            f"{level_info}"
        )

    def _clamp(self, x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    # -------------------------
    # Image handling
    # -------------------------
    def _load_or_make_placeholder(self, path: str, label: str) -> Image.Image:
        if path in self._pil_cache:
            return self._pil_cache[path]

        if os.path.exists(path):
            img = Image.open(path).convert("RGBA")
            img = img.resize((VIEW_W, VIEW_H), Image.LANCZOS)
            self._pil_cache[path] = img
            return img

        # placeholder
        img = Image.new("RGBA", (VIEW_W, VIEW_H), (40, 40, 40, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, VIEW_W - 20, VIEW_H - 20], outline=(120, 120, 120, 255), width=4)
        draw.text((40, 40), "MISSING IMAGE", fill=(220, 220, 220, 255))
        draw.text((40, 80), f"{label}", fill=(220, 220, 220, 255))
        draw.text((40, 120), f"Expected file: {os.path.basename(path)}", fill=(180, 180, 180, 255))

        self._pil_cache[path] = img
        return img

    def _load_sprite_icon(self, path: str, label: str, size=(50, 50)) -> ImageTk.PhotoImage:
        if path in self._sprite_icons:
            return self._sprite_icons[path]

        if os.path.exists(path):
            img = Image.open(path).convert("RGBA")
            img = img.resize(size, Image.LANCZOS)
        else:
            # simple placeholder for ammo icon
            img = Image.new("RGBA", size, (60, 60, 60, 255))
            draw = ImageDraw.Draw(img)
            draw.rectangle([2, 2, size[0] - 2, size[1] - 2], outline=(200, 200, 0, 255), width=2)
            draw.text((5, 5), label, fill=(255, 255, 0, 255))

        tk_img = ImageTk.PhotoImage(img)
        self._sprite_icons[path] = tk_img
        return tk_img

    def _get_view_base_image(self, view_key: str) -> Image.Image:
        if view_key in INTERNAL_VIEW_PATHS:
            return self._load_or_make_placeholder(INTERNAL_VIEW_PATHS[view_key], f"INTERNAL VIEW: {view_key}")
        if view_key in OUTSIDE_VIEW_PATHS:
            return self._load_or_make_placeholder(OUTSIDE_VIEW_PATHS[view_key], f"OUTSIDE VIEW: {view_key}")
        return self._load_or_make_placeholder(os.path.join(BASE_DIR, "missing.png"), f"UNKNOWN VIEW: {view_key}")

    # -------------------------
    # View transitions
    # -------------------------
    def _transition_to(self, view_key: str):
        self._show_view(view_key, do_fade=True)

    def _attempt_outside(self, outside_key: str):
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

        if not do_fade:
            self._draw_view_instant(view_key)
            return

        prev_img = self._render_composited_image(prev)
        next_img = self._render_composited_image(view_key)
        self._fade_transition(prev_img, next_img)

    def _draw_view_instant(self, view_key: str):
        img = self._render_composited_image(view_key)
        self._tk_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)
        self._draw_sprites_for_current_view()

    def _fade_transition(self, from_img: Image.Image, to_img: Image.Image):
        black = Image.new("RGBA", (VIEW_W, VIEW_H), (0, 0, 0, 255))

        def fade_to_black(i: int):
            if i > FADE_STEPS:
                fade_from_black(0)
                return
            t = i / FADE_STEPS
            blended = Image.blend(from_img, black, t)
            self._fade_work_img = ImageTk.PhotoImage(blended)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self._fade_work_img)
            self.after(FADE_DELAY_MS, lambda: fade_to_black(i + 1))

        def fade_from_black(i: int):
            if i > FADE_STEPS:
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
            self.after(FADE_DELAY_MS, lambda: fade_from_black(i + 1))

        fade_to_black(0)

    def _render_composited_image(self, view_key: str) -> Image.Image:
        base = self._get_view_base_image(view_key).copy()
        draw = ImageDraw.Draw(base)

        draw.rectangle([0, 0, VIEW_W, 30], fill=(0, 0, 0, 160))
        draw.text((10, 7), f"VIEW: {view_key}", fill=(255, 255, 255, 255))

        if self.level.active and view_key in ("LEFT_GUNNER", "RIGHT_GUNNER", "OUT_LEFT", "OUT_RIGHT"):
            draw.text((200, 7), "Left-click: cannon (shell). Right-click: MG (ammo).", fill=(220, 220, 220, 255))

        if view_key == "ENGINE":
            msg = "ENGINE STATUS: BROKEN / STOPPED" if self.engine_broken else "ENGINE STATUS: RUNNING/READY"
            draw.text((10, 40), msg, fill=(255, 255, 255, 255))

        return base

    # -------------------------
    # Driving / level timers
    # -------------------------
    def _start_timers_for_driving(self):
        self._cancel_timers()

        self.driving = True
        self.level.active = False
        self.engine_broken = False
        self.out_of_fuel = False

        self._update_status()

        self._fuel_tick_after_id = self.after(1000, self._fuel_tick)
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

    def _driver_stop(self):
        if not self.driving:
            return
        self._start_level(reason="Manual stop")

    def _driver_start(self):
        if self.driving:
            return

        # Only require repair if breakdown caused this level
        if self.engine_broken:
            messagebox.showinfo("Cannot start", "The engine is broken. Fix it first (Engine View -> Fix Engine).")
            return

        # Only require fuel if this level is because of fuel
        if self.out_of_fuel and self.fuel <= 0:
            messagebox.showinfo("Cannot start", "No fuel. You need to scavenge fuel before starting.")
            return

        self._start_timers_for_driving()
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

    def _start_level(self, reason: str):
        self._cancel_timers()
        self.driving = False
        self.level.active = True
        self.level.reason = reason

        self.engine_broken = (reason == "Engine breakdown")
        self.out_of_fuel = (reason == "Out of fuel")

        # Populate no man's land
        self.level.parts = max(1, random.randint(1, 3))
        self.level.fuel_cans = random.randint(1, 3)
        self.level.shells = random.randint(0, 3)
        self.level.zombies = random.randint(1, 6)
        self.level.ammo_boxes = random.randint(1, 2)

        self._populate_outside_sprites()
        self._update_status()
        self._draw_view_instant(self.current_view_key)

    def _populate_outside_sprites(self):
        for k in self.sprites_by_view:
            self.sprites_by_view[k].clear()

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
        place("ammo", self.level.ammo_boxes)

    # -------------------------
    # Sprites
    # -------------------------
    def _draw_sprites_for_current_view(self):
        if not self.level.active:
            return
        if self.current_view_key not in ("OUT_DRIVER", "OUT_LEFT", "OUT_RIGHT"):
            return

        sprites = self.sprites_by_view[self.current_view_key]
        for sp in sprites:
            if sp.kind == "ammo":
                # draw ammo icon image
                icon = self._load_sprite_icon(AMMO_SPRITE_PATH, "AMMO")
                cx = sp.x + sp.w // 2
                cy = sp.y + sp.h // 2
                sp.canvas_id = self.canvas.create_image(cx, cy, image=icon)
                self.canvas.create_text(cx, cy + 20, text="AMMO", fill="white", font=("Segoe UI", 8, "bold"))
                continue

            # other types: rectangles
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

            sp.canvas_id = self.canvas.create_rectangle(sp.x, sp.y, sp.x + sp.w, sp.y + sp.h,
                                                        fill=fill, outline="black", width=2)
            self.canvas.create_text(sp.x + sp.w // 2, sp.y + sp.h // 2,
                                    text=txt, fill="white", font=("Segoe UI", 9, "bold"))

    # -------------------------
    # Clicking: cannon / MG
    # -------------------------
    def _on_canvas_click(self, event):
        if not self.level.active:
            return
        if self.current_view_key not in ("OUT_LEFT", "OUT_RIGHT", "OUT_DRIVER"):
            return

        sprites = self.sprites_by_view[self.current_view_key]

        # find clicked zombie
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

        # Left-click: cannon (shell)
        if event.num == 1:
            if self.shells <= 0:
                messagebox.showinfo("No shells", "You have no shells left to fire the cannon.")
                return
            self.shells -= 1

        # Right-click: machine gun (ammo)
        elif event.num == 3:
            if self.ammo < MG_AMMO_COST:
                messagebox.showinfo("Not enough ammo", f"You need at least {MG_AMMO_COST} ammo to fire the machine gun.")
                return
            self.ammo -= MG_AMMO_COST
        else:
            return

        # kill zombie
        del sprites[clicked_idx]
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

        if approach == "quick":
            base = 0.75
            max_frac = 1 / 3
        elif approach == "moderate":
            base = 0.50
            max_frac = 0.50
        else:
            base = 0.33
            max_frac = 1.00

        chance = base
        chance -= self.level.zombies * ZOMBIE_PENALTY_PER_ZOMBIE
        if give_gun and self.guns > 0:
            chance += GUN_BONUS
        chance = self._clamp(chance, CHANCE_MIN, CHANCE_MAX)

        gun_committed = False
        if give_gun and self.guns > 0:
            self.guns -= 1
            gun_committed = True

        self._update_status()
        messagebox.showinfo("Scavenging", "A crew member climbs out into no man's land to scavenge...")

        survived = (random.random() < chance)

        if not survived:
            self.crew -= 1
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

        if gun_committed:
            self.guns += 1

        frac = random.random() * max_frac
        avail = self._count_remaining_items()

        got_parts = int(avail["part"] * frac)
        got_shells = int(avail["shell"] * frac)
        got_fuel_cans = int(avail["fuel"] * frac)
        got_ammo_boxes = int(avail["ammo"] * frac)

        if (got_parts + got_shells + got_fuel_cans + got_ammo_boxes) == 0 and \
           (avail["part"] + avail["shell"] + avail["fuel"] + avail["ammo"]) > 0:
            choices = []
            if avail["part"] > 0: choices.append("part")
            if avail["shell"] > 0: choices.append("shell")
            if avail["fuel"] > 0: choices.append("fuel")
            if avail["ammo"] > 0: choices.append("ammo")
            pick = random.choice(choices)
            if pick == "part":
                got_parts = 1
            elif pick == "shell":
                got_shells = 1
            elif pick == "fuel":
                got_fuel_cans = 1
            else:
                got_ammo_boxes = 1

        fuel_gained = 0
        for _ in range(got_fuel_cans):
            fuel_gained += random.randint(FUEL_CAN_MIN, FUEL_CAN_MAX)

        ammo_gained = got_ammo_boxes * AMMO_PER_BOX

        self.parts += got_parts
        self.shells += got_shells
        self.fuel += fuel_gained
        self.ammo += ammo_gained

        self._remove_items_from_map("part", got_parts)
        self._remove_items_from_map("shell", got_shells)
        self._remove_items_from_map("fuel", got_fuel_cans)
        self._remove_items_from_map("ammo", got_ammo_boxes)

        self._update_status()
        self._draw_view_instant(self.current_view_key)

        messagebox.showinfo(
            "Returned",
            "The scavenger returns, mud-streaked and breathing hard.\n\n"
            f"Gains:\n"
            f"  Parts: +{got_parts}\n"
            f"  Shells: +{got_shells}\n"
            f"  Fuel: +{fuel_gained}\n"
            f"  Ammo: +{ammo_gained}\n\n"
            f"Survival chance was: {int(chance * 100)}%"
        )

    def _count_remaining_items(self) -> Dict[str, int]:
        counts = {"fuel": 0, "part": 0, "shell": 0, "zombie": 0, "ammo": 0}
        for sprites in self.sprites_by_view.values():
            for sp in sprites:
                if sp.kind in counts:
                    counts[sp.kind] += 1
        return counts

    def _remove_items_from_map(self, kind: str, n: int):
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