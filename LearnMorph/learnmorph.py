"""
LearnMorph — implement-and-evaluate loop.

Every stage runs as:   produce(feedback) -> evaluate() -> pass? advance : retry with feedback
State is written to runs/<run_id>/ after every stage, so re-running resumes where it stopped.

Usage:
    export ANTHROPIC_API_KEY=...
    python learnmorph.py --config config.json --run demo1

config.json:
{
  "teachers": {
    "3b1b":     {"sources": ["data/3b1b/*.txt"]},
    "lecturer": {"sources": ["data/lecturer/*.txt"]}
  },
  "topic": "Why does the derivative of e^x equal itself?",
  "target_beats": 7,
  "n_candidates": 4,
  "max_rounds": 3
}
Optional "style" block (defaults shown; see STYLE below):
  "style": {"habit_caps": true, "plan_budget": true, "sentence_length": true, "honest_gate": false,
            "heldout_sources": []}
--honest-gate turns on the excerpt-only reranking judge. LM_CACHE_DIR=<dir> caches every API response.
Sources are plain-text transcripts (one file per video). Optionally, a source may be a YouTube URL;
it will be fetched with youtube-transcript-api if installed.
"""

import argparse
import hashlib
import glob
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

# --------------------------------------------------------------------------- config
WRITER_MODEL = os.getenv("LM_WRITER_MODEL", "claude-sonnet-5-5")
JUDGE_MODEL = os.getenv("LM_JUDGE_MODEL", "claude-sonnet-5-5")
# Sonnet 5 thinks adaptively by default and can spend the whole output budget
# thinking (stop_reason=max_tokens, no text). Low effort keeps that bounded.
EFFORT = os.getenv("LM_EFFORT", "low")
API_KEY = os.getenv("ANTHROPIC_API_KEY") or sys.exit("ANTHROPIC_API_KEY not set")


# Optional response cache (set LM_CACHE_DIR): identical prompts return the stored reply, so reruns cost nothing.
CACHE_DIR = Path(os.environ["LM_CACHE_DIR"]) if os.getenv("LM_CACHE_DIR") else None
if CACHE_DIR:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


class _APIError(Exception):
    pass

BEAT_TAXONOMY = {
    "hook": "Opens with a puzzle, surprise, or concrete question",
    "misconception": "States the intuitive-but-wrong idea and lets it sit",
    "concrete_example": "Works one specific case fully",
    "visual": "Describes what to look at or imagine — the picture in words",
    "generalize": "Moves from the example to the rule",
    "reprise": "Returns to the hook with the new understanding",
    "caveat": "Flags a limit or 'it's more subtle than that'",
    "bridge": "Transition between sub-ideas",
    "exercise": "Hands the viewer something to try",
    "meta": "Comments on the learning process itself",
}

RUBRIC = {
    "move_fidelity": "Does this beat do what the grammar says this beat type does?",
    "device_usage": "Are the teacher's signature devices present at roughly the teacher's frequency?",
    "sentence_texture": "Do length, rhythm, person, and hedging match the teacher's sentence traits?",
    "anti_generic": "Could this be mistaken for the generic_rewrite column? 5 = never, 1 = indistinguishable",
    "continuity": "Does it follow the previous beat and set up the next?",
}

ACCEPT_AVG, ACCEPT_MIN = 4.0, 3


# --------------------------------------------------------------------------- llm helpers
def llm(system, user, model=WRITER_MODEL, temperature=0.7, max_tokens=6000):
    """Raw Messages API call via urllib (no SDK: the sandbox can't pip install)."""
    payload = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
               "system": system, "messages": [{"role": "user", "content": user}]}
    body = json.dumps(payload).encode()
    cf = CACHE_DIR / f"{hashlib.sha256(body).hexdigest()[:24]}.json" if CACHE_DIR else None
    if cf and cf.exists():
        return json.loads(cf.read_text())["text"]
    text = _llm_uncached(payload, body)
    if not text.strip():
        raise _APIError(f"empty text from {model}")
    if cf:
        cf.write_text(json.dumps({"model": model, "text": text}))
        with open(CACHE_DIR / "calls.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {model}\n")
    return text


def _llm_uncached(payload, body):
    for attempt in range(4):
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            return "".join(b["text"] for b in data["content"] if b["type"] == "text")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:500]
            if e.code == 400 and "temperature" in msg and "temperature" in payload:
                del payload["temperature"]; body = json.dumps(payload).encode(); continue
            if e.code in (400, 401, 403, 404):
                raise _APIError(f"{e.code}: {msg}")
            if attempt == 3:
                raise _APIError(f"{e.code} after retries: {msg}")
            time.sleep(3 * 2 ** attempt)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3:
                raise
            time.sleep(3 * 2 ** attempt)


def llm_json(system, user, **kw):
    """Ask for JSON only; strip fences; one repair retry on parse failure."""
    system = system + "\nRespond with valid JSON only. No prose, no markdown fences."
    txt = llm(system, user, **kw)
    for candidate in (txt, re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    fixed = llm("Return ONLY the following content as valid JSON. Fix syntax, change nothing else.",
                txt, model=kw.get("model", WRITER_MODEL), temperature=0)
    return json.loads(re.sub(r"^```(?:json)?|```$", "", fixed.strip(), flags=re.M))


# --------------------------------------------------------------------------- state
class Run:
    def __init__(self, run_id, cfg):
        self.cfg = cfg
        self.root = Path("runs") / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "log.md"

    def path(self, *parts):
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save(self, obj, *parts):
        p = self.path(*parts)
        if isinstance(obj, str):
            p.write_text(obj)
        else:
            p.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
        return p

    def load(self, *parts):
        p = self.root.joinpath(*parts)
        if not p.exists():
            return None
        txt = p.read_text()
        return json.loads(txt) if p.suffix == ".json" else txt

    def log(self, msg):
        line = f"- {time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------- the loop
def step_loop(run, name, produce, evaluate, max_rounds, out_parts):
    """Generic implement→evaluate→retry loop. Returns accepted output or best-effort after max_rounds."""
    cached = run.load(*out_parts)
    if cached is not None:
        run.log(f"[{name}] cached, skipping")
        return cached
    feedback, best, best_score = None, None, float("-inf")
    for rnd in range(1, max_rounds + 1):
        out = produce(feedback)
        ev = evaluate(out)  # {"score": float, "pass": bool, "feedback": str}
        run.log(f"[{name}] round {rnd}: score={ev['score']:.2f} pass={ev['pass']} — {ev['feedback'][:120]}")
        run.save({"round": rnd, "eval": ev, "output": out}, "attempts", f"{name}_r{rnd}.json")
        if ev["score"] > best_score:
            best, best_score = out, ev["score"]
        if ev["pass"]:
            run.save(out, *out_parts)
            return out
        feedback = ev["feedback"]
    run.log(f"[{name}] FAILED gate after {max_rounds} rounds; keeping best (score={best_score:.2f})")
    run.save(best, *out_parts)
    return best


# --------------------------------------------------------------------------- stage 0: corpus
def load_corpus(run, teacher, sources):
    texts = []
    for s in sources:
        if s.startswith("http"):
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
                vid = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", s).group(1)
                t = " ".join(x["text"] for x in YouTubeTranscriptApi.get_transcript(vid))
                texts.append({"source": s, "text": t})
            except Exception as e:
                run.log(f"[corpus:{teacher}] could not fetch {s}: {e}")
        else:
            for f in sorted(glob.glob(s)):
                texts.append({"source": f, "text": Path(f).read_text()})
    if len(texts) < 2:
        sys.exit(f"Need at least 2 transcripts for {teacher}, found {len(texts)}")
    run.save(texts, "corpus", f"{teacher}.json")
    run.log(f"[corpus:{teacher}] {len(texts)} transcripts, {sum(len(t['text']) for t in texts)//1000}k chars")
    return texts


# --------------------------------------------------------------------------- stage A: move grammar
def stage_grammar(run, teacher, corpus, max_rounds):
    tax = json.dumps(BEAT_TAXONOMY, indent=1)

    def produce(feedback):
        segmented = []
        for doc in corpus:
            seg = llm_json(
                f"You segment teaching transcripts into pedagogical beats.\nBeat taxonomy:\n{tax}\n"
                "Every span of the transcript maps to exactly one beat. If a recurring pattern fits nothing, "
                "add a new label and include 'proposed_new_label': true with a reason.",
                f"Transcript ({doc['source']}):\n\n{doc['text'][:60000]}\n\n"
                'Return {"beats":[{"beat":label,"start_quote":first 8 words,"summary":one line,'
                '"devices":[signature devices seen: rhetorical question, second person, named character, '
                'callback, self-correction, pause word, joke, etc]}]}',
                temperature=0.2)
            segmented.append({"source": doc["source"], **seg})
        run.save(segmented, "profiles", teacher, "segmented.json")
        fb = f"\nReviewer feedback from the previous attempt — fix these:\n{feedback}\n" if feedback else ""
        return llm_json(
            "You turn segmented transcripts into a MOVE GRAMMAR: a recipe a writer could follow to reproduce "
            "this teacher's style WITHOUT seeing the originals. Rules: every claim must be backed by a count, "
            "position, or verbatim example. No unsupported adjectives (no 'engaging', 'intuitive', 'clear')." + fb,
            f"Segmented sources:\n{json.dumps(segmented)[:80000]}\n\n"
            "Return {\n"
            ' "beat_sequences": [[beat,...] per source],\n'
            ' "beat_frequency": {beat: fraction of all beats},\n'
            ' "typical_position": {beat: "opening|early|middle|late|closing"},\n'
            ' "transitions": {beat: {next_beat: count}},\n'
            ' "signature_devices": [{"device":..., "count":..., "example": verbatim}],\n'
            ' "sentence_traits": {"avg_len": n, "person": "...", "hedging_words": [...], "jargon_density": "low|med|high"},\n'
            ' "recipe": "8-15 imperative sentences a writer follows to write like this teacher"\n}',
            temperature=0.2)

    def evaluate(grammar):
        ev = llm_json(
            "You audit a style grammar. Be strict.",
            f"Grammar:\n{json.dumps(grammar)}\n\nScore 1-5 each:\n"
            "1 evidence: every trait has a count/position/example (no bare adjectives)\n"
            "2 recipe_usability: could a writer follow 'recipe' without seeing the originals?\n"
            "3 specificity: would this grammar distinguish this teacher from a generic explainer?\n"
            'Return {"scores":{...},"feedback":"concrete list of what to fix"}',
            model=JUDGE_MODEL, temperature=0)
        s = ev["scores"]
        avg = sum(s.values()) / len(s)
        return {"score": avg, "pass": avg >= 4 and min(s.values()) >= 3, "feedback": ev["feedback"]}

    return step_loop(run, f"grammar:{teacher}", produce, evaluate, max_rounds,
                     ("profiles", teacher, "move_grammar.json"))


def grammars_too_similar(run, g1, g2, name1, name2):
    """Programmatic gate: if beat-frequency vectors nearly match, the taxonomy is too coarse."""
    keys = set(g1["beat_frequency"]) | set(g2["beat_frequency"])
    v1 = [g1["beat_frequency"].get(k, 0) for k in keys]
    v2 = [g2["beat_frequency"].get(k, 0) for k in keys]
    dot = sum(a * b for a, b in zip(v1, v2))
    n1, n2 = sum(a * a for a in v1) ** .5, sum(b * b for b in v2) ** .5
    cos = dot / (n1 * n2) if n1 and n2 else 1
    run.log(f"[grammar-diff] cosine({name1},{name2}) = {cos:.3f}")
    return cos > 0.97


# --------------------------------------------------------------------------- stage B: exemplars
def stage_exemplars(run, teacher, corpus, grammar, max_rounds):
    def produce(feedback):
        fb = f"\nFix from previous attempt:\n{feedback}\n" if feedback else ""
        return llm_json(
            "You build a CONTRASTIVE EXEMPLAR BANK. For each beat type present in the grammar, choose the "
            "strongest verbatim excerpt (2-6 sentences, ONE beat type) and write a generic_rewrite that "
            "conveys the same information the way a bland textbook would." + fb,
            f"Grammar:\n{json.dumps(grammar)[:20000]}\n\nTranscripts:\n"
            + "\n\n---\n\n".join(d["text"][:25000] for d in corpus)
            + '\n\nReturn {"pairs":[{"beat_type":...,"teacher_excerpt":verbatim,"generic_rewrite":...,'
              '"what_makes_it_distinctive":"1-2 sentences naming the concrete difference"}]} with 8-15 pairs.',
            temperature=0.3)

    def evaluate(bank):
        needed = {b for b, f in grammar["beat_frequency"].items() if f >= 0.05}
        have = {p["beat_type"] for p in bank["pairs"]}
        missing = needed - have
        ev = llm_json(
            "You audit contrastive pairs.",
            f"Pairs:\n{json.dumps(bank)}\n\nFor the bank as a whole, score 1-5:\n"
            "1 contrast_clarity: is the difference obvious at a glance?\n"
            "2 verbatim: do teacher_excerpts look like real transcript speech, not paraphrase?\n"
            "3 same_content: does each rewrite keep the same information?\n"
            'Return {"scores":{...},"feedback":"..."}',
            model=JUDGE_MODEL, temperature=0)
        s = ev["scores"]
        avg = sum(s.values()) / len(s)
        fb = ev["feedback"] + (f" MISSING beat types: {sorted(missing)}" if missing else "")
        return {"score": avg - len(missing), "pass": avg >= 4 and not missing, "feedback": fb}

    return step_loop(run, f"exemplars:{teacher}", produce, evaluate, max_rounds,
                     ("profiles", teacher, "exemplars.json"))


# --------------------------------------------------------------------------- style controls (measured in code)
# Defaults; override in config.json under "style", or pass --honest-gate.
#   habit_caps:      per-1,000-word budgets for countable habits and structural devices, enforced in code
#   plan_budget:     plan stage gets the same structural budgets; beat order must occur in the real sequences
#   sentence_length: candidates outside the teacher's sentence-length band (or over-joined with "and") are rejected
#   honest_gate:     (off) rerank with a judge that sees only real excerpts, never the grammar. Costs ~3x calls.
#   heldout_sources: substrings of corpus sources to keep away from every writer-side measurement
STYLE = {"habit_caps": True, "plan_budget": True, "sentence_length": True, "honest_gate": False,
         "heldout_sources": []}
GATE_MODEL = os.getenv("LM_GATE_MODEL", "claude-opus-5-5")
GATE_PASS = 6
sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_traits as st


def train_docs(corpus):
    docs = [d for d in corpus if not any(h in d["source"] for h in STYLE["heldout_sources"])]
    return [{"src": Path(d["source"]).stem, "text": st.norm(d["text"])} for d in docs]


def _excerpts(corpus, n, size, seed):
    rng, docs, out = random.Random(seed), train_docs(corpus), []
    for _ in range(n):
        ss = st.sentences(rng.choice(docs)["text"])
        i, cur = rng.randrange(max(1, len(ss) - 10)), []
        while i < len(ss) and len(" ".join(cur).split()) < size:
            cur.append(ss[i]); i += 1
        out.append(" ".join(cur))
    return out


def style_targets(run, teacher, corpus, grammar, planned_words):
    """Habit/device rates per 1,000 words and the sentence band, from the real (non-held-out) transcripts."""
    cached = run.load("profiles", teacher, "style_targets.json")
    if cached:  # rescale budgets if the plan's length differs from the estimate they were made for
        for kind in ("countable", "model_counted"):
            cached[f"{kind}_budget"] = {k: int(round(r * planned_words / 1000))
                                        for k, r in cached[f"{kind}_rates_per_1000w"].items()}
        cached["planned_words"] = planned_words
        return cached
    docs = train_docs(corpus)
    train = " ".join(d["text"] for d in docs)
    n_words = len(train.split())
    rates = st.per_k(train)
    names = [d["device"] for d in grammar.get("signature_devices", [])]
    counted = llm_json("You count rhetorical devices in a transcript. Count every occurrence; be literal.",
                       f"Devices: {json.dumps(names)}\n\nTranscript ({n_words} words):\n{train}\n\n"
                       'Return {"counts":{device: integer}}', temperature=0)["counts"] if names else {}
    model_rates = {k: round(1000 * float(v) / n_words, 2) for k, v in counted.items()}
    seqs = grammar.get("beat_sequences", [])
    tgt = {"train_sources": [d["src"] for d in docs], "train_words": n_words, "planned_words": planned_words,
           "countable_rates_per_1000w": rates,
           "countable_budget": {k: int(round(r * planned_words / 1000)) for k, r in rates.items()},
           "model_counted_rates_per_1000w": model_rates,
           "model_counted_budget": {k: int(round(r * planned_words / 1000)) for k, r in model_rates.items()},
           "sentence_band": st.sentence_band(docs),
           "real_transitions": sorted({f"{a}>{b}" for s in seqs for a, b in zip(s, s[1:])}),
           "real_openers": sorted({s[0] for s in seqs if s})}
    run.save(tgt, "profiles", teacher, "style_targets.json")
    return tgt


def budget_block(tgt, used):
    rem = {k: max(0, v - used.get(k, 0)) for k, v in tgt["countable_budget"].items()}
    return rem, ("HABIT BUDGET for the REST of the whole script (real rate per 1,000 words in brackets). "
                 "A candidate that exceeds a hard limit is rejected automatically:\n"
                 + "\n".join(f"- {k}: {rem[k]} left ({tgt['countable_rates_per_1000w'][k]}/1000w)" for k in rem)
                 + "\nSoft budget for the whole script (spread across beats, never cluster):\n"
                 + "\n".join(f"- {k}: {v} ({tgt['model_counted_rates_per_1000w'][k]}/1000w)"
                             for k, v in tgt["model_counted_budget"].items()) + "\n")


def sentence_block(tgt):
    b = tgt["sentence_band"]
    return (f"SENTENCE LENGTH (checked in code): this teacher's mean sentence length is {b['per_transcript_means']} "
            f"words per transcript. Each candidate's mean must fall in {b['lo']}-{b['hi']} words. Do not reach it by "
            f"gluing clauses with ', and' / ', so' / ', but' (max {b['joiner_max']['comma_joined_clauses']} per 1,000 "
            "words); build long sentences the way the excerpts do.\n")


# --------------------------------------------------------------------------- stage C: plan
def stage_plan(run, teacher, topic, grammar, n_beats, max_rounds, corpus=None):
    tgt = style_targets(run, teacher, corpus, grammar, n_beats * 150) if STYLE["plan_budget"] and corpus else None
    if tgt:
        sb = {k: tgt["countable_budget"][k] for k in st.STRUCTURAL}
        tidy_budget = sum(sb.values())
        controls = (f"\nSTRUCTURAL BUDGET for the whole lesson, from how this teacher really moves between ideas "
                    f"(per 1,000 words: { {k: tgt['countable_rates_per_1000w'][k] for k in st.STRUCTURAL} }): {sb}. "
                    "Do not plan a beat whose job is a recap, summary, preview, signpost, a coined name for a rule "
                    "or a numbered list unless this budget allows it. Do not make beats symmetrical or tidy. Real "
                    "lessons loop back, revisit an earlier example and repeat themselves; you may do that.\n"
                    f"Allowed beat-to-beat moves (seen in the real lessons): {', '.join(tgt['real_transitions'])}. "
                    f"Allowed opening beats: {tgt['real_openers']}.\n")
    else:
        controls, tidy_budget = "", None

    def produce(feedback):
        fb = f"\nFix from previous attempt:\n{feedback}\n" if feedback else ""
        return llm_json(
            "You plan a lesson as an ordered list of beats, following a teacher's move grammar: their typical "
            "opening beat, their transition patterns, their typical positions. Every beat needs a SPECIFIC "
            "example or picture — no placeholders." + controls + fb,
            f"Topic: {topic}\nNumber of beats: {n_beats}\nGrammar:\n{json.dumps(grammar)}\n\n"
            'Return {"beats":[{"i":1,"beat":label,"goal":one line,"example_or_visual":specific,"target_words":n}]}',
            temperature=0.5)

    def _normalize(plan):
        for k, x in enumerate(plan.get("beats", [])):
            x["i"] = k + 1
        return plan

    def evaluate(plan):
        _normalize(plan)
        problems = []
        if tgt:  # code checks: real transitions and structural budget
            seq = [b["beat"] for b in plan["beats"]]
            bad = [f"{a}>{b}" for a, b in zip(seq, seq[1:]) if f"{a}>{b}" not in tgt["real_transitions"]]
            if bad:
                problems.append(f"beat moves never seen in the real lessons: {bad}")
            if seq and seq[0] not in tgt["real_openers"]:
                problems.append(f"opening beat '{seq[0]}' not one of {tgt['real_openers']}")
            tidy = sum(len(re.findall(st.PLAN_TIDY, (b["goal"] + " " + b["example_or_visual"]).lower()))
                       for b in plan["beats"])
            if tidy > tidy_budget:
                problems.append(f"plan asks for {tidy} recap/preview/label/list devices, budget {tidy_budget}")
        ev = llm_json(
            "You audit a lesson plan. Do NOT reward tidiness, symmetry, neat recaps or memorable labels; "
            "looping back and redundancy are fine." if tgt else "You audit a lesson plan against a move grammar.",
            (f"Plan:\n{json.dumps(plan)}\n\nScore 1-5:\n"
             "1 specificity: does every beat have its own concrete example or picture (not 'an example')?\n"
             "2 coverage: does the plan actually teach the topic?\n" if tgt else
             f"Grammar transitions/positions:\n{json.dumps({k: grammar[k] for k in ('transitions', 'typical_position', 'beat_frequency')})}\n"
             f"Plan:\n{json.dumps(plan)}\n\nScore 1-5:\n"
             "1 follows_transitions: does beat order match the teacher's transition patterns?\n"
             "2 specificity: is every example_or_visual concrete (not 'an example')?\n"
             "3 coverage: does the plan actually teach the topic?\n")
            + 'Return {"scores":{...},"feedback":"..."}',
            model=JUDGE_MODEL, temperature=0)
        s = ev["scores"]
        avg = sum(s.values()) / len(s)
        ok = avg >= 4 and min(s.values()) >= 3 and not problems
        return {"score": avg - len(problems), "pass": ok, "feedback": "; ".join(problems + [ev["feedback"]])}

    out = step_loop(run, f"plan:{teacher}", produce, evaluate, max_rounds, ("plans", f"{teacher}.json"))
    return _normalize(out)


# --------------------------------------------------------------------------- stage D: beats (write → check → judge → rerank)
def relevant_pairs(bank, beat_type, k=4):
    same = [p for p in bank["pairs"] if p["beat_type"] == beat_type]
    other = [p for p in bank["pairs"] if p["beat_type"] != beat_type]
    return (same + other)[:k]


def honest_gate(corpus, other_corpus, prev, cands, seed):
    own, alt = _excerpts(corpus, 3, 200, f"gate-{seed}"), _excerpts(other_corpus, 2, 200, f"gate-alt-{seed}")
    return llm_json(
        "You are an expert at recognising a specific human teacher's voice and at spotting AI-written imitations.",
        "Real transcript excerpts from TEACHER T (the target):\n" + "\n---\n".join(own)
        + "\n\nReal excerpts from a DIFFERENT teacher, for contrast:\n" + "\n---\n".join(alt)
        + f"\n\nThe lesson so far ends with:\n{prev[-900:]}\n\nCandidates for the next passage:\n"
        + "\n\n".join(f"[{i}] {c}" for i, c in cands)
        + "\n\nScore each candidate 1-10: how plausible is it that this passage was transcribed from teacher T's own "
          "video? Ignore subject matter. Penalise heavily anything that reads as machine-scripted: tidy parallel "
          "structure, staged or over-used habits, too many rhetorical questions, slogan-like lines, uniform sentence "
          "length, neat summaries.\n"
          'Return {"scores":[{"idx":n,"score":1-10,"tells":"short"}],"feedback":"what reads as machine-written"}',
        model=GATE_MODEL, temperature=0)


def structure_check(b, cands):
    out = llm_json(
        "You check whether lesson passages do a planned job. Judge function only, not style or quality.",
        f"Beat type '{b['beat']}': {BEAT_TAXONOMY.get(b['beat'], '')}\nGoal: {b['goal']}\n"
        f"Planned example/visual: {b['example_or_visual']}\n\nCandidates:\n"
        + "\n\n".join(f"[{i}] {c}" for i, c in cands)
        + '\n\nReturn {"pass":[indices that do the job],"why_fail":"one line on the failures"}', temperature=0)
    return {int(i) for i in out.get("pass", [])}, out.get("why_fail", "")


def stage_beats(run, teacher, plan, grammar, bank, n_cand, max_rounds, corpus=None, other_corpus=None):
    need = (STYLE["habit_caps"] or STYLE["sentence_length"]) and corpus
    planned = sum(int(b.get("target_words", 150)) for b in plan["beats"])
    tgt = style_targets(run, teacher, corpus, grammar, planned) if need else None
    accepted = run.load("scripts", f"{teacher}_beats.json") or []
    done = {x["i"] for x in accepted}
    for b in plan["beats"]:
        if b["i"] in done:
            continue
        name = f"beat:{teacher}:{b['i']}"
        prev = accepted[-1]["text"] if accepted else "(this is the opening)"
        nxt = next((x for x in plan["beats"] if x["i"] == b["i"] + 1), None)
        pairs = relevant_pairs(bank, b["beat"])
        recipe_bits = {k: grammar[k] for k in ("recipe", "signature_devices", "sentence_traits")}
        words = int(b.get("target_words", 150))
        used = {}
        for x in accepted:
            for k, v in st.device_counts(x["text"]).items():
                used[k] = used.get(k, 0) + v
        remaining, bblock = budget_block(tgt, used) if tgt and STYLE["habit_caps"] else ({}, "")
        sblock = sentence_block(tgt) if tgt and STYLE["sentence_length"] else ""
        rnd = {"n": 0}

        def produce(feedback, b=b, prev=prev, pairs=pairs):
            rnd["n"] += 1
            fb = f"\nThe last batch was rejected. Notes:\n{feedback}\nProduce candidates that fix this and differ from each other.\n" if feedback else ""
            out = llm_json(
                f"You write ONE lesson beat in a specific teacher's style.\n"
                f"1) THE RECIPE for this teacher:\n{json.dumps(recipe_bits)}\n"
                f"   This beat's type is '{b['beat']}': {BEAT_TAXONOMY.get(b['beat'], '')}\n"
                f"2) EXAMPLES. Write like teacher_excerpt, NOT like generic_rewrite:\n{json.dumps(pairs)}\n"
                + bblock + sblock +
                "3) Continue from what came before. No headings, no meta-commentary, no markdown.\n"
                f"Produce {n_cand} candidates that differ meaningfully from each other." + fb,
                f"Previous beat:\n{prev}\n\nThis beat — goal: {b['goal']}\nUse this example/visual: {b['example_or_visual']}\n"
                f"Target length ~{words} words.\n"
                f"Next beat will be: {nxt['goal'] if nxt else '(end)'}\n\n"
                'Return {"candidates":["...","..."]}',
                temperature=0.9)
            return {"cands": out["candidates"], "winner": None, "score": 0}

        def evaluate(out, b=b, prev=prev, pairs=pairs):
            cands, notes = list(enumerate(out["cands"])), []
            if remaining:  # habit caps: hard reject in code
                ok = []
                for i, c in cands:
                    over = {k: v - remaining[k] for k, v in st.device_counts(c).items() if v > remaining.get(k, 0)}
                    (ok.append((i, c)) if not over else notes.append(f"cand {i} over budget {over}"))
                if not ok:
                    worst = min(cands, key=lambda ic: sum(max(0, v - remaining.get(k, 0)) for k, v in st.device_counts(ic[1]).items()))
                    out.update(winner=worst[1], score=0)
                    return {"score": -10, "pass": False, "feedback": "All candidates exceeded the habit budget: "
                            + "; ".join(notes) + ". Use FEWER of these habits."}
                cands = ok
            if sblock:  # sentence length + conjunction joining: hard reject in code, keep the closest
                checked = [(i, c, *st.band_check(c, tgt["sentence_band"])) for i, c in cands]
                ok = [(i, c) for i, c, good, _, _ in checked if good]
                if not ok:
                    i, c, _, d, _ = min(checked, key=lambda x: x[3])
                    out.update(winner=c, score=0)
                    return {"score": -1 - d, "pass": False, "feedback": "Rejected in code: "
                            + "; ".join(f"cand {i}: {m}" for i, _, _, _, m in checked)}
                notes += [f"cand {i}: {m}" for i, _, good, _, m in checked if not good]
                cands = ok
            if STYLE["honest_gate"] and other_corpus:
                passed, why = structure_check(b, cands)
                good = [(i, c) for i, c in cands if i in passed]
                if not good:
                    out.update(winner=cands[0][1], score=0)
                    return {"score": -0.5, "pass": False, "feedback": f"No candidate did the beat's job: {why}"}
                g = honest_gate(corpus, other_corpus, prev, good, f"{teacher}-{b['i']}-{rnd['n']}")
                ranked = sorted(((float(s["score"]), int(s["idx"]), s.get("tells", "")) for s in g["scores"]
                                 if int(s["idx"]) in dict(good)), reverse=True)
                best, idx, tells = ranked[0]
                run.save({"ranked": ranked, "candidates": out["cands"], "notes": notes},
                         "scores", teacher, f"beat_{b['i']}_r{rnd['n']}.json")
                out.update(winner=dict(good)[idx], score=best / 2)  # 1-10 -> 1-5 scale
                return {"score": best, "pass": best >= GATE_PASS, "feedback": g.get("feedback", "") + f" Best: {tells}"}
            scored = llm_json(
                "You judge STYLE ONLY, not correctness. First reread the exemplar pairs so you know what "
                "generic drift looks like. Score each candidate on every rubric item 1-5.",
                f"Rubric:\n{json.dumps(RUBRIC)}\nTeacher recipe:\n{json.dumps(recipe_bits)}\n"
                f"Exemplar pairs:\n{json.dumps(pairs)}\nBeat type: {b['beat']}\nPrevious beat:\n{prev}\n\n"
                f"Candidates:\n{json.dumps(cands)}\n\n"
                'Return {"scores":[{"idx":n,"items":{rubric_key:score},"justification":"one line"}],'
                '"feedback":"what all candidates got wrong, concretely"}',
                model=JUDGE_MODEL, temperature=0)
            ranked = []
            for s in scored.get("scores", []):
                vals = [float(v) for v in s.get("items", {}).values() if isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit()]
                if vals and int(s["idx"]) in dict(cands):
                    ranked.append((sum(vals) / len(vals), min(vals), int(s["idx"]), str(s.get("justification", ""))))
            if not ranked:  # unparseable judge output: accept the first candidate that passed the code checks
                out.update(winner=cands[0][1], score=ACCEPT_AVG)
                return {"score": 0, "pass": False, "feedback": "judge returned no numeric scores; rescore"}
            ranked.sort(reverse=True)
            avg, mn, idx, why = ranked[0]
            run.save({"ranked": ranked, "candidates": out["cands"], "notes": notes},
                     "scores", teacher, f"beat_{b['i']}_r{rnd['n']}.json")
            out.update(winner=dict(cands)[idx], score=avg)
            return {"score": avg, "pass": avg >= ACCEPT_AVG and mn >= ACCEPT_MIN, "feedback": scored["feedback"]}

        best = step_loop(run, name, produce, evaluate, max_rounds, ("candidates", teacher, f"beat_{b['i']}.json"))
        accepted.append({"i": b["i"], "beat": b["beat"], "text": best["winner"], "score": best["score"]})
        run.save(accepted, "scripts", f"{teacher}_beats.json")
    return accepted


# --------------------------------------------------------------------------- stage E: assemble + drift
def stage_assemble(run, teacher, beats, grammar, bank, plan, n_cand, max_rounds):
    script = "\n\n".join(x["text"] for x in beats)
    scores = [x["score"] for x in beats]
    third = max(1, len(scores) // 3)
    drift = (sum(scores[:third]) / third) - (sum(scores[-third:]) / third)
    run.log(f"[assemble:{teacher}] drift (first third − last third) = {drift:.2f}")
    if drift > 0.5 and not STYLE["sentence_length"] and not STYLE["habit_caps"]:  # regeneration only in legacy mode
        run.log(f"[assemble:{teacher}] drift detected → regenerating last third with opening beat as anchor")
        anchor = beats[0]["text"]
        tail_plan = {"beats": plan["beats"][-third:]}
        for b in tail_plan["beats"]:
            b["goal"] = f"(Anchor to this voice: {anchor[:400]}) " + b["goal"]
            for p in ("candidates", "scores"):
                f = run.root / p / teacher / f"beat_{b['i']}.json"
                if f.exists():
                    f.unlink()
        new_tail = stage_beats(run, teacher, tail_plan, grammar, bank, n_cand, max_rounds)
        beats = beats[:-third] + new_tail
        script = "\n\n".join(x["text"] for x in beats)
    smoothed = llm(
        "Smooth transitions between these beats. Change as few words as possible; do NOT change voice, "
        "devices, or sentence texture. Return only the script.",
        script, temperature=0.2)
    tgt = run.load("profiles", teacher, "style_targets.json")
    if tgt and STYLE["sentence_length"]:  # smoothing must not undo the code-enforced sentence band
        if st.band_check(script, tgt["sentence_band"])[1] < st.band_check(smoothed, tgt["sentence_band"])[1]:
            run.log(f"[assemble:{teacher}] smoothing moved sentence length out of band; keeping unsmoothed")
            smoothed = script
    run.save(smoothed, "scripts", f"{teacher}.md")
    run.save(beats, "scripts", f"{teacher}_beats.json")
    return smoothed


# --------------------------------------------------------------------------- stage F: blind validation
def stage_validate(run, scripts, grammars, trials=10):
    names = list(scripts)
    if len(names) != 2:
        run.log("[validate] need exactly two teachers"); return None
    a, b = names
    hits, per_trial = 0, []
    for t in range(trials):
        order = [a, b] if random.random() < 0.5 else [b, a]
        ev = llm_json(
            "You are given two teachers' move grammars and two anonymous lesson scripts on the same topic. "
            "Decide which script belongs to which teacher. Style only.",
            f"Teacher X grammar:\n{json.dumps(grammars[a])[:8000]}\n\nTeacher Y grammar:\n{json.dumps(grammars[b])[:8000]}\n\n"
            f"Script 1:\n{scripts[order[0]]}\n\nScript 2:\n{scripts[order[1]]}\n\n"
            'Return {"script1":"X"|"Y","script2":"X"|"Y","confidence":0-1,"most_telling_beat":"..."}',
            model=JUDGE_MODEL, temperature=0.7)
        correct = (ev["script1"] == "X") == (order[0] == a)
        hits += correct
        per_trial.append({"order": order, "verdict": ev, "correct": correct})
    acc = hits / trials
    verdict = "PASS" if acc >= 0.9 else "STRENGTHEN grammar+exemplars, rerun from plan" if acc >= 0.6 else "FAIL: return to extraction, add sources"
    report = {"accuracy": acc, "verdict": verdict, "trials": per_trial}
    run.save(report, "validation", "report.json")
    run.log(f"[validate] accuracy={acc:.0%} → {verdict}")
    return report


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--stop-after", choices=["grammar", "exemplars", "plan", "beats", "assemble"], default=None)
    ap.add_argument("--honest-gate", action="store_true", help="rerank beats with the excerpt-only judge (off by default)")
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    STYLE.update(cfg.get("style", {}))
    STYLE["honest_gate"] = STYLE["honest_gate"] or args.honest_gate
    run = Run(args.run, cfg)
    R = cfg.get("max_rounds", 3)
    teachers = list(cfg["teachers"])

    corpus, grammars = {}, {}
    for t in teachers:
        corpus[t] = run.load("corpus", f"{t}.json") or load_corpus(run, t, cfg["teachers"][t]["sources"])
        grammars[t] = stage_grammar(run, t, corpus[t], R)
    if len(teachers) == 2 and grammars_too_similar(run, grammars[teachers[0]], grammars[teachers[1]], *teachers):
        run.log("[gate] grammars nearly identical → beat taxonomy too coarse. Extend BEAT_TAXONOMY and rerun.")
        sys.exit(1)
    if args.stop_after == "grammar":
        return

    banks = {t: stage_exemplars(run, t, corpus[t], grammars[t], R) for t in teachers}
    if args.stop_after == "exemplars":
        return

    plans = {t: stage_plan(run, t, cfg["topic"], grammars[t], cfg.get("target_beats", 7), R, corpus[t]) for t in teachers}
    if args.stop_after == "plan":
        return

    other = {t: next((corpus[u] for u in teachers if u != t), None) for t in teachers}
    beats = {t: stage_beats(run, t, plans[t], grammars[t], banks[t], cfg.get("n_candidates", 4), R, corpus[t], other[t])
             for t in teachers}
    if args.stop_after == "beats":
        return

    scripts = {t: stage_assemble(run, t, beats[t], grammars[t], banks[t], plans[t], cfg.get("n_candidates", 4), R)
               for t in teachers}
    if args.stop_after == "assemble":
        return

    stage_validate(run, scripts, grammars)
    run.log(f"done → {run.root}")


if __name__ == "__main__":
    main()
