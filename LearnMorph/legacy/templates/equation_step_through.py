"""LearnMorph Manim template: equation_step_through.

Template-constrained per CLAUDE.md rule 2 — the STRUCTURE is FIXED. Only the
slot values are overridden by per-scene drivers; construct() is never edited.

visual_hint keywords this template fits: "algebra step", "one move", "add and
subtract", "highlight term", "rewrite step", "factor", "simplify", "identity".

WHY this template exists (review feedback: "equations not explained well"): the old
equation_transform jumps A -> B in one morph. Real teaching shows ONE algebraic
change at a time with the CHANGING term visually called out. Here the equation
is built from PARTS (tex substrings), the beat morphs parts_a -> parts_b with
TransformMatchingTex so unchanged parts glide, and the parts listed in
highlight_b render in the profile's ACCENT color while everything else stays in
the primary color. One beat = one move.

Beat-fit (P1 of the Phase-3 quality sprint): `target_duration` is the beat's
NARRATION length. construct() fits itself: if the natural animation is shorter
it rests on the final frame for the remainder (calm hold, on-message for the
style); if longer it compresses uniformly (floored). The template can therefore
never overflow its narration by more than the floor allows — and the generator
has a hard guard + DoD check that fails the build if it somehow would.

Defaults are neutral sentinels (grey on near-black), NOT a hand-picked palette:
a driver that forgets a slot fails visibly (closed-loop rule from Phase 2).
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


class EquationStepThrough(Scene):
    # --- Content slots (overridden per beat by the storyboard) ---
    # parts_a / parts_b: tex substrings composing the before/after equations.
    # Empty parts_b = "show-only" beat (present parts_a, no morph).
    # highlight_a / highlight_b: indices (into the respective parts tuple) drawn
    # in the ACCENT color — the term the narration is talking about.
    parts_a: tuple = (r"a", r"+b")
    parts_b: tuple = ()
    highlight_a: tuple = ()
    highlight_b: tuple = ()
    caption_text: str = ""

    # --- Style slots (from the Style Profile via conditioning.py) ---
    primary_color: str = "#808080"
    accent_color: str = "#FFFFFF"
    bg_color: str = "#202020"
    caption_font: str = "Helvetica"
    equation_font_size: int = 64
    caption_font_size: int = 28

    # --- Timing slots (profile-scaled) + beat fit ---
    write_run_time: float = 1.5
    caption_run_time: float = 1.0
    settle_wait: float = 0.5
    morph_run_time: float = 2.0
    hold_wait: float = 1.0
    fade_run_time: float = 0.8
    # target_duration: this beat's narration length in seconds. 0 = natural pace.
    target_duration: float = 0.0
    _MIN_COMPRESS: float = 0.5  # never play faster than half speed

    def _colored(self, parts: tuple, highlights: tuple) -> MathTex:
        """Build a MathTex from parts, accenting the highlighted indices."""
        eq = MathTex(*parts, font_size=self.equation_font_size)
        for i, sub in enumerate(eq.submobjects):
            sub.set_color(self.accent_color if i in highlights else self.primary_color)
        return eq

    def natural_duration(self) -> float:
        """Unscaled seconds of the full beat animation (no terminal rest)."""
        total = self.write_run_time + self.settle_wait
        if self.caption_text:
            total += self.caption_run_time
        if self.parts_b:
            total += self.morph_run_time + self.settle_wait
        total += self.hold_wait + self.fade_run_time
        return total

    def _fit(self) -> tuple[float, float]:
        """(compress_factor, terminal_rest_seconds) to hit target_duration.

        Shorter-than-narration animation rests on the final frame (k=1, rest>0);
        longer-than-narration compresses uniformly (k<1, floored at
        _MIN_COMPRESS). One source of truth used by construct() and by the
        generator's predicted-duration report.
        """
        if self.target_duration <= 0:
            return 1.0, 0.0
        natural = self.natural_duration()
        if natural <= self.target_duration:
            return 1.0, self.target_duration - natural
        return max(self._MIN_COMPRESS, self.target_duration / natural), 0.0

    def fitted_duration(self) -> float:
        """Total seconds this beat will actually render."""
        k, rest = self._fit()
        return self.natural_duration() * k + rest

    def construct(self) -> None:
        self.camera.background_color = self.bg_color
        k, rest = self._fit()

        eq_a = self._colored(self.parts_a, self.highlight_a)
        caption = Text(
            self.caption_text,
            font=self.caption_font,
            color=self.accent_color,
            font_size=self.caption_font_size,
        )
        VGroup(eq_a, caption).arrange(DOWN, buff=0.9)

        self.play(Write(eq_a), run_time=self.write_run_time * k, rate_func=rf.smooth)
        if self.caption_text:
            self.play(Create(caption), run_time=self.caption_run_time * k, rate_func=rf.smooth)
        self.wait(self.settle_wait * k)

        end_eq = eq_a
        if self.parts_b:
            eq_b = self._colored(self.parts_b, self.highlight_b)
            eq_b.move_to(eq_a)
            self.play(
                TransformMatchingTex(eq_a, eq_b),
                run_time=self.morph_run_time * k,
                rate_func=rf.ease_in_out_sine,
            )
            self.wait(self.settle_wait * k)
            end_eq = eq_b

        self.wait(self.hold_wait * k + rest)
        if self.caption_text:
            self.play(
                FadeOut(end_eq), FadeOut(caption), run_time=self.fade_run_time * k, rate_func=rf.smooth
            )
        else:
            self.play(FadeOut(end_eq), run_time=self.fade_run_time * k, rate_func=rf.smooth)
