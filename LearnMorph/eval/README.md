# Style evaluation

Tests whether generated scripts sound like the real teachers, rather than just following the recipe.
Findings are in `report.md` (plain-words table, conclusions, limitations) and summarised in `../docs/STATUS.md`.

Files
- `eval_style.py`: the five tests (attribution without the recipe, real-text ceiling, unstyled control, real vs generated, beat structure).
- `luar_score.py`: a non-LLM authorship check. Written, never run (Hugging Face was blocked).
- `report.md`, `results.json`: results. `results.json` holds scores, verdicts and the judge's one-line reasons
  (these quote at most short phrases, longest about 130 characters). It holds no transcript excerpts, so it is
  committed unreduced. The two unstyled control texts in it were written by the model, not taken from a teacher.

Not committed: `cache/` (every raw API response, which embeds the real transcript excerpts shown to the judge).

Rerun
- `eval_style.py` and `../style_traits.py` take every path from arguments; see the usage block at the top of `eval_style.py`.
- Needs `data/<teacher>/*.txt` (local only, see the main README) and the scripts to test, passed with `--script NAME=TEACHER=PATH`.
- Set `ANTHROPIC_API_KEY`. Responses are cached in `./eval_cache`, so a rerun is free. The first full run made about 166 API calls.
- `results.json` and `report.md` are from the first evaluation (runs `demo1` and `demo2`); `results_D.json` is the writer experiment (run `demo3`).
- `luar_score.py` still has a hardcoded data path at the top; change it before running.
