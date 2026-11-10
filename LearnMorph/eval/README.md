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
- The scripts were written for a container layout: both hardcode `/home/claude/run2` as the project root
  (`RUN2` in `eval_style.py`, the data path in `luar_score.py`). Change those to this folder's parent.
- That root needs `learnmorph.py`, `data/<teacher>/*.txt` (local only, see the main README) and `runs/demo1`, `runs/demo2` scripts.
- Set `ANTHROPIC_API_KEY`, then `python eval_style.py`. Without the cache, a full run makes about 166 API calls.
