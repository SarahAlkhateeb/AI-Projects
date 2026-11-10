"""LearnMorph Manim template: area_model.

Template-constrained per CLAUDE.md rule 2 — the STRUCTURE is FIXED. Only the
slot values are overridden by per-scene drivers. A driver subclasses AreaModel
and reassigns the class attributes; it never edits the construct() body.

WHY this template exists: the equation_transform template animates equation TEXT
only and shows NO geometry, so a reviewer scored the "completing the square"
demo visual_match=2/10. This template realizes the profile's layout_pattern
("geometric object on left, equation/annotation on right") by DRAWING the
classic area model for completing the square — the square of side x, the two
b/2 rectangles that split the bx term, and the small corner square that
LITERALLY completes the larger square. The algebra on the right updates in sync
with a TransformMatchingTex morph, the 3b1b move.

As with equation_transform, EVERY style and timing slot is a parameter driven
from the EXTRACTED Style Profile via conditioning.visual_params(). The defaults
are deliberately NEUTRAL sentinels (grey on near-black), NOT a hand-picked 3b1b
palette: a driver that forgets to set a slot fails visibly rather than silently
shipping a borrowed look.
"""

from manim import (
    DL,
    DOWN,
    LEFT,
    RIGHT,
    UP,
    UR,
    Brace,
    Create,
    FadeIn,
    FadeOut,
    MathTex,
    Rectangle,
    Scene,
    Square,
    Text,
    Transform,
    TransformMatchingTex,
    VGroup,
    Write,
)


class AreaModel(Scene):
    # --- Content slots (overridden per scene by the script's visual_hint) ---
    # side_label: the symbolic side length of the big square (the "x" in x^2).
    # split_value: half the linear coefficient b — the width of each attached
    #   rectangle and the side of the completing corner square (the "b/2").
    side_label: str = "x"
    split_value: str = "3"
    caption_text: str = ""

    # --- Style slots (overridden by conditioning.py from the Style Profile) ---
    # Sentinel defaults: neutral grey, NOT a hand-picked 3b1b palette. If a
    # driver leaves these unset the render looks obviously wrong, which is the
    # signal that the loop was not actually closed.
    primary_color: str = "#808080"  # the x*x square + equation
    accent_color: str = "#FFFFFF"  # caption + completing corner + braces
    bg_color: str = "#202020"  # background
    caption_font: str = "Helvetica"
    equation_font_size: int = 40
    caption_font_size: int = 26
    label_font_size: int = 28

    # --- Timing slots (driven from audio pace / pause pattern) ---
    write_run_time: float = 1.5
    caption_run_time: float = 1.0
    settle_wait: float = 0.5
    morph_run_time: float = 2.0
    hold_wait: float = 1.0
    fade_run_time: float = 0.8

    # --- Beat-stage slots (Phase-3 micro-beats: one sentence = one visual) ---
    # stage: "full" preserves the original 3-beat scene. "square" / "strips" /
    # "corner" render ONE geometric micro-beat each: earlier stages' geometry is
    # pre-added STATICALLY (so consecutive beats cut together seamlessly), only
    # this beat's addition animates, and there is NO fade-out (the next beat
    # re-draws the same state, so holding the last frame gives continuity).
    # Staged mode shows geometry only — the algebra lives in
    # equation_step_through beats, keeping one idea on screen at a time.
    # target_duration: this beat's narration length; the stage fits itself
    # (rest on the final frame if short, compress uniformly if long).
    stage: str = "full"
    target_duration: float = 0.0
    _MIN_COMPRESS: float = 0.5

    # --- Narration-anchor slots (full mode only; Whisper word timestamps) ---
    # anchor_offset_seconds: when (from scene start) the narration speaks the
    # anchor word for the KEY event — here, the corner square that literally
    # COMPLETES the big square (beat 3). construct() inserts a lead-in wait so
    # the corner drops in as the word lands. 0.0 = no anchoring.
    # post_anchor_scale: multiplies every beat AFTER the anchor so the punchline
    # fits the narration remaining after the word (no mid-animation trims).
    # post_anchor_hold: extra breath after the punchline (visual polish).
    anchor_offset_seconds: float = 0.0
    post_anchor_scale: float = 1.0
    post_anchor_hold: float = 0.4
    _MIN_SETTLE: float = 0.1  # floor when compressing settles to reach an early anchor

    def stage_natural_duration(self) -> float:
        """Unscaled seconds of the selected micro-beat's animation."""
        total = self.write_run_time + self.settle_wait + self.hold_wait
        if self.stage == "square":
            total += self.caption_run_time  # side labels fade in
        elif self.stage == "corner":
            total += self.caption_run_time + self.morph_run_time  # brace + outline
        if self.caption_text:
            total += self.caption_run_time
        return total

    def _stage_fit(self) -> tuple[float, float]:
        """(compress_factor, terminal_rest) so the micro-beat hits
        target_duration. Same contract as EquationStepThrough._fit."""
        if self.target_duration <= 0:
            return 1.0, 0.0
        natural = self.stage_natural_duration()
        if natural <= self.target_duration:
            return 1.0, self.target_duration - natural
        return max(self._MIN_COMPRESS, self.target_duration / natural), 0.0

    def fitted_duration(self) -> float:
        """Total seconds this staged beat will actually render."""
        k, rest = self._stage_fit()
        return self.stage_natural_duration() * k + rest

    def _settle_times(self) -> tuple[float, float]:
        """Effective settle waits for beats 1 and 2, compressed when the anchor
        word is spoken EARLIER than the natural lead-in.

        WHY: the corner cannot start before beats 1-2 finish. If the narration
        reaches the anchor word first, the only deterministic way to catch up is
        to shave the two settle pauses (down to a floor) — the drawn animations
        keep their profile-driven pace. Split the shave evenly across both.
        """
        base = self.settle_wait
        natural = (
            self.write_run_time + self.caption_run_time + base
            + self.write_run_time + self.morph_run_time + base
        )
        a = self.anchor_offset_seconds
        if a <= 0 or a >= natural:
            return base, base
        deficit = natural - a
        shave = min(deficit, 2 * max(0.0, base - self._MIN_SETTLE))
        return base - shave / 2, base - shave / 2

    def anchor_lead_in(self) -> float:
        """EFFECTIVE seconds before the corner-fill (beat 3) can start, i.e.
        after settle compression. One source of truth shared by construct()
        and the generator's sync report — no estimate drift."""
        s1, s2 = self._settle_times()
        beat1 = self.write_run_time + self.caption_run_time + s1
        beat2 = self.write_run_time + self.morph_run_time + s2
        return beat1 + beat2

    def post_anchor_natural(self) -> float:
        """Unscaled seconds from the anchor (corner Create) to scene end."""
        total = (
            self.write_run_time  # corner Create
            + self.caption_run_time  # brace + area label
            + self.morph_run_time  # eq2 -> eq3
            + self.morph_run_time  # outline punchline
            + self.hold_wait
            + self.post_anchor_hold
            + self.fade_run_time
        )
        if self.caption_text:
            total += self.caption_run_time
        return total

    def construct(self) -> None:
        self.camera.background_color = self.bg_color

        # --- Geometry parameterized off a base unit so it fits 854x480 -------
        # The big square is BASE wide; each attached rectangle is BASE * SPLIT
        # wide. BASE is chosen so the whole assembled figure stays inside the
        # left half of the frame with margin.
        base = 2.4  # side of the x*x square in scene units
        split = 0.7  # width of the b/2 rectangles, as a fraction of base
        rect_w = base * split

        # Anchor the assembled figure on the LEFT of the frame. The full
        # assembled square is base + rect_w tall; anchoring its bottom-left low
        # keeps the top rectangles and the corner brace inside the frame.
        left_anchor = LEFT * 3.3 + DOWN * 1.7

        # The x*x square (bottom-left of the assembly).
        x_square = Square(side_length=base)
        x_square.set_stroke(self.primary_color, width=3)
        x_square.set_fill(self.primary_color, opacity=0.25)
        x_square.move_to(left_anchor, aligned_edge=DL)

        # Rectangle attached to the RIGHT side (one b/2 split of bx).
        right_rect = Rectangle(width=rect_w, height=base)
        right_rect.set_stroke(self.accent_color, width=3)
        right_rect.set_fill(self.primary_color, opacity=0.12)
        right_rect.next_to(x_square, RIGHT, buff=0)
        right_rect.align_to(x_square, DOWN)

        # Rectangle attached to the TOP side (the other b/2 split of bx).
        top_rect = Rectangle(width=base, height=rect_w)
        top_rect.set_stroke(self.accent_color, width=3)
        top_rect.set_fill(self.primary_color, opacity=0.12)
        top_rect.next_to(x_square, UP, buff=0)
        top_rect.align_to(x_square, LEFT)

        # The completing corner square (b/2 x b/2) — the visual punchline.
        corner = Square(side_length=rect_w)
        corner.set_stroke(self.accent_color, width=3)
        corner.set_fill(self.accent_color, opacity=0.30)
        corner.next_to(top_rect, RIGHT, buff=0)
        corner.align_to(top_rect, DOWN)

        # --- Side-length labels (kept readable, off the shapes) --------------
        x_label_left = MathTex(
            self.side_label, color=self.primary_color, font_size=self.label_font_size
        )
        x_label_left.next_to(x_square, LEFT, buff=0.2)
        x_label_bottom = MathTex(
            self.side_label, color=self.primary_color, font_size=self.label_font_size
        )
        x_label_bottom.next_to(x_square, DOWN, buff=0.2)
        split_label = MathTex(
            self.split_value, color=self.accent_color, font_size=self.label_font_size
        )
        split_label.next_to(right_rect, RIGHT, buff=0.2)

        # --- Micro-beat branch: render exactly ONE geometric stage -----------
        if self.stage != "full":
            k, rest = self._stage_fit()
            caption = Text(
                self.caption_text,
                font=self.caption_font,
                color=self.accent_color,
                font_size=self.caption_font_size,
            )
            # Layout pattern from the profile: geometry left, annotation right.
            caption.move_to(RIGHT * 3.2)

            if self.stage == "square":
                self.play(Create(x_square), run_time=self.write_run_time * k)
                self.play(
                    FadeIn(x_label_left), FadeIn(x_label_bottom),
                    run_time=self.caption_run_time * k,
                )
            elif self.stage == "strips":
                # Earlier state appears already-settled: seamless cut from the
                # previous beat, which ended holding this exact frame.
                self.add(x_square, x_label_left, x_label_bottom)
                self.play(
                    Create(right_rect), Create(top_rect), FadeIn(split_label),
                    run_time=self.write_run_time * k,
                )
            elif self.stage == "corner":
                self.add(
                    x_square, x_label_left, x_label_bottom,
                    right_rect, top_rect, split_label,
                )
                self.play(Create(corner), run_time=self.write_run_time * k)
                corner_brace = Brace(corner, direction=UR, color=self.accent_color)
                brace_area = MathTex(
                    self.split_value, "^2",
                    color=self.accent_color, font_size=self.label_font_size,
                )
                brace_area.next_to(corner_brace, UR, buff=0.1)
                self.play(
                    FadeIn(corner_brace), FadeIn(brace_area),
                    run_time=self.caption_run_time * k,
                )
                completed = Square(side_length=base + rect_w)
                completed.set_stroke(self.accent_color, width=5)
                completed.set_fill(opacity=0)
                completed.move_to(x_square, aligned_edge=DL)
                outline = x_square.copy().set_fill(opacity=0).set_stroke(self.accent_color, width=5)
                self.play(Transform(outline, completed), run_time=self.morph_run_time * k)
            else:
                raise ValueError(f"unknown stage {self.stage!r}")

            if self.caption_text:
                self.play(Write(caption), run_time=self.caption_run_time * k)
            self.wait(self.settle_wait * k)
            # Rest on the final frame for the remainder of the narration. NO
            # fade-out: the next beat re-draws this state, so holding gives a
            # seamless cut instead of a blink.
            self.wait(self.hold_wait * k + rest)
            return

        # --- Algebra on the RIGHT, updated in three synced stages ------------
        s = self.split_value
        eq_size = self.equation_font_size
        eq_anchor = RIGHT * 2.6 + UP * 0.2

        eq1 = MathTex(self.side_label, "^2", color=self.primary_color, font_size=eq_size)
        eq2 = MathTex(
            self.side_label,
            "^2",
            "+",
            "2",
            r"\cdot",
            s,
            self.side_label,
            color=self.primary_color,
            font_size=eq_size,
        )
        eq3 = MathTex(
            "(",
            self.side_label,
            "+",
            s,
            ")",
            "^2",
            color=self.primary_color,
            font_size=eq_size,
        )
        for eq in (eq1, eq2, eq3):
            eq.move_to(eq_anchor)

        # Caption beneath the algebra (the narration's claim, if any).
        caption = Text(
            self.caption_text,
            font=self.caption_font,
            color=self.accent_color,
            font_size=self.caption_font_size,
        )
        if self.caption_text:
            # Sit the caption below the algebra, aligned to the same column.
            caption.move_to(eq_anchor + DOWN * 1.4)

        # --- Animate: build the figure left, narrate the algebra right -------
        # Beat 1: draw the x*x square and show x^2. Settles are the COMPRESSED
        # values so an early anchor word can still be met (see _settle_times).
        s1, s2 = self._settle_times()
        self.play(Create(x_square), run_time=self.write_run_time)
        self.play(
            FadeIn(x_label_left),
            FadeIn(x_label_bottom),
            Write(eq1),
            run_time=self.caption_run_time,
        )
        self.wait(s1)

        # Beat 2: attach the two b/2 rectangles (split of the bx term) and
        # grow the algebra to x^2 + 2*split*x.
        self.play(
            Create(right_rect),
            Create(top_rect),
            FadeIn(split_label),
            run_time=self.write_run_time,
        )
        self.play(TransformMatchingTex(eq1, eq2), run_time=self.morph_run_time)
        self.wait(s2)

        # Narration anchor: hold the settled two-beat frame until the narration
        # speaks the anchor word, so the corner-fill starts exactly on it.
        extra = max(0.0, self.anchor_offset_seconds - self.anchor_lead_in())
        if extra > 0:
            self.wait(extra)

        # Beat 3 (post-anchor, scaled to fit the remaining narration): drop in
        # the corner square that LITERALLY completes the big square; brace it
        # with its (split)^2 area; morph algebra to (x+split)^2.
        k = self.post_anchor_scale
        self.play(Create(corner), run_time=self.write_run_time * k)
        corner_brace = Brace(corner, direction=UR, color=self.accent_color)
        brace_area = MathTex(s, "^2", color=self.accent_color, font_size=self.label_font_size)
        brace_area.next_to(corner_brace, UR, buff=0.1)
        self.play(FadeIn(corner_brace), FadeIn(brace_area), run_time=self.caption_run_time * k)
        self.play(TransformMatchingTex(eq2, eq3), run_time=self.morph_run_time * k)

        # Outline the now-complete (x+split) square to land the punchline.
        completed = Square(side_length=base + rect_w)
        completed.set_stroke(self.accent_color, width=5)
        completed.set_fill(opacity=0)
        completed.move_to(x_square, aligned_edge=DL)
        outline = x_square.copy().set_fill(opacity=0).set_stroke(self.accent_color, width=5)
        self.play(Transform(outline, completed), run_time=self.morph_run_time * k)

        if self.caption_text:
            self.play(Write(caption), run_time=self.caption_run_time * k)
        self.wait((self.hold_wait + self.post_anchor_hold) * k)

        # Soft exit.
        figure = VGroup(
            x_square,
            right_rect,
            top_rect,
            corner,
            outline,
            x_label_left,
            x_label_bottom,
            split_label,
            corner_brace,
            brace_area,
            eq3,
        )
        if self.caption_text:
            self.play(FadeOut(figure), FadeOut(caption), run_time=self.fade_run_time * k)
        else:
            self.play(FadeOut(figure), run_time=self.fade_run_time * k)
