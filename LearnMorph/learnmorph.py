"""
LearnMorph — implement-and-evaluate loop.

Every stage runs as:   produce(feedback) -> evaluate() -> pass? advance : retry with feedback
State is written to runs/<run_id>/ after every stage, so re-running resumes where it stopped.

Usage:
    pip install anthropic
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
Sources are plain-text transcripts (one file per video). Optionally, a source may be a YouTube URL;
it will be fetched with youtube-transcript-api if installed.
"""

import argparse
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
    payload = {"model": model, "max_tokens": max_tokens, "system": system,
               "messages": [{"role": "user", "content": user}]}
    if temperature is not None:
        payload["temperature"] = temperature
    body = json.dumps(payload).encode()
    for attempt in range(4):
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            return "".join(b["text"] for b in data["content"] if b["type"] == "text")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:500]
            if e.code == 400 and "temperature" in msg and temperature is not None:
                return llm(system, user, model=model, temperature=None, max_tokens=max_tokens)
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
    feedback, best, best_score = None, None, -1
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


# --------------------------------------------------------------------------- stage C: plan
def stage_plan(run, teacher, topic, grammar, n_beats, max_rounds):
    def produce(feedback):
        fb = f"\nFix from previous attempt:\n{feedback}\n" if feedback else ""
        return llm_json(
            "You plan a lesson as an ordered list of beats, following a teacher's move grammar: their typical "
            "opening beat, their transition patterns, their typical positions. Every beat needs a SPECIFIC "
            "example or picture — no placeholders." + fb,
            f"Topic: {topic}\nNumber of beats: {n_beats}\nGrammar:\n{json.dumps(grammar)}\n\n"
            'Return {"beats":[{"i":1,"beat":label,"goal":one line,"example_or_visual":specific,"target_words":n}]}',
            temperature=0.5)

    def evaluate(plan):
        ev = llm_json(
            "You audit a lesson plan against a move grammar.",
            f"Grammar transitions/positions:\n{json.dumps({k: grammar[k] for k in ('transitions', 'typical_position', 'beat_frequency')})}\n"
            f"Plan:\n{json.dumps(plan)}\n\nScore 1-5:\n"
            "1 follows_transitions: does beat order match the teacher's transition patterns?\n"
            "2 specificity: is every example_or_visual concrete (not 'an example')?\n"
            "3 coverage: does the plan actually teach the topic?\n"
            'Return {"scores":{...},"feedback":"..."}',
            model=JUDGE_MODEL, temperature=0)
        s = ev["scores"]
        avg = sum(s.values()) / len(s)
        return {"score": avg, "pass": avg >= 4 and min(s.values()) >= 3, "feedback": ev["feedback"]}

    return step_loop(run, f"plan:{teacher}", produce, evaluate, max_rounds,
                     ("plans", f"{teacher}.json"))


# --------------------------------------------------------------------------- stage D: beats (write → judge → rerank)
def relevant_pairs(bank, beat_type, k=4):
    same = [p for p in bank["pairs"] if p["beat_type"] == beat_type]
    other = [p for p in bank["pairs"] if p["beat_type"] != beat_type]
    return (same + other)[:k]


def stage_beats(run, teacher, plan, grammar, bank, n_cand, max_rounds):
    accepted = []
    for b in plan["beats"]:
        name = f"beat:{teacher}:{b['i']}"
        prev = accepted[-1]["text"] if accepted else "(this is the opening)"
        nxt = next((x for x in plan["beats"] if x["i"] == b["i"] + 1), None)
        pairs = relevant_pairs(bank, b["beat"])
        recipe_bits = {k: grammar[k] for k in ("recipe", "signature_devices", "sentence_traits")}

        def produce(feedback, b=b, prev=prev, pairs=pairs):
            fb = f"\nA reviewer rejected the last batch. Their notes:\n{feedback}\nProduce candidates that are MORE varied in opening device and example.\n" if feedback else ""
            out = llm_json(
                f"You write ONE lesson beat in a specific teacher's style.\n"
                f"1) THE RECIPE for this teacher:\n{json.dumps(recipe_bits)}\n"
                f"   This beat's type is '{b['beat']}': {BEAT_TAXONOMY.get(b['beat'], '')}\n"
                f"2) EXAMPLES. Write like teacher_excerpt, NOT like generic_rewrite:\n{json.dumps(pairs)}\n"
                "3) Continue from what came before. No headings, no meta-commentary, no markdown.\n"
                f"Produce {n_cand} candidates that differ meaningfully from each other." + fb,
                f"Previous beat:\n{prev}\n\nThis beat — goal: {b['goal']}\nUse this example/visual: {b['example_or_visual']}\n"
                f"Target length ~{b.get('target_words', 150)} words.\n"
                f"Next beat will be: {nxt['goal'] if nxt else '(end)'}\n\n"
                'Return {"candidates":["...","..."]}',
                temperature=0.9)
            return out["candidates"]

        def evaluate(cands, b=b, prev=prev, pairs=pairs):
            scored = llm_json(
                "You judge STYLE ONLY, not correctness. First reread the exemplar pairs so you know what "
                "generic drift looks like. Score each candidate on every rubric item 1-5.",
                f"Rubric:\n{json.dumps(RUBRIC)}\nTeacher recipe:\n{json.dumps(recipe_bits)}\n"
                f"Exemplar pairs:\n{json.dumps(pairs)}\nBeat type: {b['beat']}\nPrevious beat:\n{prev}\n\n"
                f"Candidates:\n{json.dumps(list(enumerate(cands)))}\n\n"
                'Return {"scores":[{"idx":n,"items":{rubric_key:score},"justification":"one line"}],'
                '"feedback":"what all candidates got wrong, concretely"}',
                model=JUDGE_MODEL, temperature=0)
            ranked = []
            for s in scored["scores"]:
                vals = list(s["items"].values())
                ranked.append((sum(vals) / len(vals), min(vals), s["idx"], s["justification"]))
            ranked.sort(reverse=True)
            avg, mn, idx, why = ranked[0]
            run.save({"ranked": ranked, "candidates": cands}, "scores", teacher, f"beat_{b['i']}.json")
            spread = ranked[0][0] - ranked[-1][0] if len(ranked) > 1 else 1
            fb = scored["feedback"] + (" Candidates were too similar to each other." if spread < 0.5 else "")
            ok = avg >= ACCEPT_AVG and mn >= ACCEPT_MIN
            return {"score": avg, "pass": ok, "feedback": fb, "best": {"idx": idx, "avg": avg, "min": mn, "why": why}}

        # step_loop stores the candidate list; pull the winner from the last saved score file
        cands = step_loop(run, name, produce, evaluate, max_rounds, ("candidates", teacher, f"beat_{b['i']}.json"))
        sc = run.load("scores", teacher, f"beat_{b['i']}.json")
        best_idx = sc["ranked"][0][2]
        accepted.append({"i": b["i"], "beat": b["beat"], "text": cands[best_idx], "score": sc["ranked"][0][0]})
        run.save(accepted, "scripts", f"{teacher}_beats.json")
    return accepted


# --------------------------------------------------------------------------- stage E: assemble + drift
def stage_assemble(run, teacher, beats, grammar, bank, plan, n_cand, max_rounds):
    script = "\n\n".join(x["text"] for x in beats)
    scores = [x["score"] for x in beats]
    third = max(1, len(scores) // 3)
    drift = (sum(scores[:third]) / third) - (sum(scores[-third:]) / third)
    run.log(f"[assemble:{teacher}] drift (first third − last third) = {drift:.2f}")
    if drift > 0.5:
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
    args = ap.parse_args()
    cfg = json.load(open(args.config))
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

    plans = {t: stage_plan(run, t, cfg["topic"], grammars[t], cfg.get("target_beats", 7), R) for t in teachers}
    if args.stop_after == "plan":
        return

    beats = {t: stage_beats(run, t, plans[t], grammars[t], banks[t], cfg.get("n_candidates", 4), R) for t in teachers}
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
