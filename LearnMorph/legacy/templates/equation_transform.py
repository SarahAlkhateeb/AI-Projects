"""LearnMorph Manim template: equation_transform.

Template-constrained per CLAUDE.md rule 2 — the STRUCTURE is FIXED. Only the
slot values are overridden by per-scene drivers. A driver subclasses
EquationTransform and reassigns the class attributes; it never edits the
construct() body.

Phase 2 — "close the loop": EVERY style slot below is a parameter, and every
parameter is driven from the EXTRACTED Style Profile (palette, fonts, timing).
There are deliberately NO hardcoded 3b1b color literals or magic timings in
this file — the defaults are neutral sentinels so that a driver which forgets
to set a slot fails visibly rather than silently shipping a hand-picked look.
The morph uses TransformMatchingTex so shared symbols glide into place (the
signature 3b1b "equation morph").

Narration anchoring (v4 quality sprint): the scene's KEY event is the morph.
`anchor_offset_seconds` (from Whisper word timestamps on OUR OWN generated
narration) tells the template when the anchor word is spoken; construct()
inserts a lead-in wait so the morph STARTS on that word. Deterministic: the
template knows its own beat arithmetic, so the wait is exact, not estimated.
"""

from manim import (
    DOWN,
    Create,
    FadeOut,
    MathTex,
    Scene,
    Text,
    TransformMatchingTex,
    VGroup,
    Write,
)
from manim import rate_functions as rf


class EquationTransform(Scene):
    # --- Content slots (overridden per scene by the script's visual_hint) ---
    equation_a: str = r"a + b"
    equation_b: str = r"b + a"
    caption_text: str = ""

    # --- Style slots (overridden by conditioning.py from the Style Profile) ---
    # Sentinel defaults: neutral grey, NOT a hand-picked 3b1b palette. If a
    # driver leaves these unset the render looks obviously wrong, which is the
    # signal that the loop was not actually closed.
    primary_color: str = "#808080"  # equation color
    accent_color: str = "#FFFFFF"  # caption color
    bg_color: str = "#202020"  # background
    caption_font: str = "Helvetica"
    equation_font_size: int = 72
    caption_font_size: int = 30

    # --- Timing slots (driven from audio pace / pause pattern) ---
    write_run_time: float = 1.5
    caption_run_time: float = 1.0
    settle_wait: float = 0.5
    morph_run_time: float = 2.0
    hold_wait: float = 1.0
    fade_run_time: float = 0.8

    # --- Narration-anchor slots (driven from Whisper word timestamps) ---
    # anchor_offset_seconds: when (from scene start) the narration speaks the
    # anchor word for the KEY event — here, the equation morph. construct()
    # inserts a lead-in wait so the morph STARTS as the word lands. 0.0 = no
    # anchoring (the morph runs at its natural beat position).
    # post_anchor_scale: multiplies every beat AFTER the anchor so the rest of
    # the animation FITS inside the remaining narration time instead of being
    # trimmed mid-animation by the assembler (the generator computes it from
    # audio_duration - anchor_time).
    # post_anchor_hold: a slightly longer breath AFTER the key moment so the
    # punchline rests on screen (visual-polish request, part of the fixed beat).
    anchor_offset_seconds: float = 0.0
    post_anchor_scale: float = 1.0
    post_anchor_hold: float = 0.4

    def anchor_lead_in(self) -> float:
        """Seconds of animation that elapse BEFORE the morph can start.

        WHY a method on the template: only the template knows its own beat
        structure. Drivers/generators call this to predict when the anchor
        animation will actually start (for the sync report), and construct()
        uses the same arithmetic — one source of truth, no drift.
        """
        lead = self.write_run_time + self.settle_wait
        if self.caption_text:
            lead += self.caption_run_time
        return lead

    def post_anchor_natural(self) -> float:
        """Unscaled seconds of animation FROM the anchor (morph) to scene end.
        The generator divides the remaining narration time by this to compute
        post_anchor_scale — same single-source-of-truth idea as anchor_lead_in.
        """
        return self.morph_run_time + self.hold_wait + self.post_anchor_hold + self.fade_run_time

    def construct(self) -> None:
        self.camera.background_color = self.bg_color

        eq_a = MathTex(self.equation_a, color=self.primary_color, font_size=self.equation_font_size)
        eq_b = MathTex(self.equation_b, color=self.primary_color, font_size=self.equation_font_size)

        caption = Text(
            self.caption_text,
            font=self.caption_font,
            color=self.accent_color,
            font_size=self.caption_font_size,
        )
        # Place the caption below where the equation sits.
        VGroup(eq_a, caption).arrange(DOWN, buff=1.0)
        eq_b.move_to(eq_a)  # morph target sits exactly on the source

        # Pedagogy beat: write the equation, let it breathe, reveal the caption,
        # then morph in place (the 3b1b move), then hold. All eased (smooth /
        # ease-in-out) — no linear pops.
        self.play(Write(eq_a), run_time=self.write_run_time, rate_func=rf.smooth)
        if self.caption_text:
            self.play(Create(caption), run_time=self.caption_run_time, rate_func=rf.smooth)
        self.wait(self.settle_wait)

        # Narration anchor: if the anchor word lands after our natural lead-in,
        # hold the settled frame until the word is spoken, so the morph starts
        # exactly on it. max(0, ...) means an early anchor degrades gracefully.
        extra = max(0.0, self.anchor_offset_seconds - self.anchor_lead_in())
        if extra > 0:
            self.wait(extra)

        # Post-anchor beats are scaled so the whole punchline FITS the narration
        # that remains after the anchor word (no mid-animation trims downstream).
        k = self.post_anchor_scale
        self.play(
            TransformMatchingTex(eq_a, eq_b),
            run_time=self.morph_run_time * k,
            rate_func=rf.ease_in_out_sine,
        )
        self.wait((self.hold_wait + self.post_anchor_hold) * k)
        if self.caption_text:
            self.play(
                FadeOut(eq_b), FadeOut(caption), run_time=self.fade_run_time * k, rate_func=rf.smooth
            )
        else:
            self.play(FadeOut(eq_b), run_time=self.fade_run_time * k, rate_func=rf.smooth)
