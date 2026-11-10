"""
LearnMorph style eval — non-circular checks that generated lessons sound like the REAL teacher.

Tests (see report.md for results):
  1 recipe-free attribution  judge sees real excerpts of X and Y (no grammar), then a generated script
  2 ceiling control          same, anonymous text is a held-out real chunk (different video)
  3 unstyled control         plain Sonnet explainer with no style info, run through test 1
  4 real-vs-generated        which of two ~300-word chunks is the real human transcript? (+ cleaned variant)
  5 beat structure           segment texts into beats, compare frequency/bigram distributions (no judge)

Run:  set -a; . /home/claude/run2/.env; set +a; python3 eval_style.py
Every API response is cached in cache/ so a rerun is free. LM_JUDGE_PROVIDER selects the judge backend.
"""
import hashlib, json, math, os, random, re, sys
from collections import Counter
from pathlib import Path

RUN2 = Path("/home/claude/run2")
sys.path.insert(0, str(RUN2))
import learnmorph as lm  # reuse raw-urllib llm() and BEAT_TAXONOMY

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"; CACHE.mkdir(exist_ok=True)
WRITER, JUDGE_MODEL = "claude-sonnet-5-5", "claude-opus-5-5"
SEED, N_ATTR, N_CEIL, N_PAIR, N_PAIR_UNSTYLED = 1234, 10, 10, 5, 3
MAX_CALLS = int(os.getenv("LM_MAX_CALLS", "200"))
TEACHERS = ["3b1b", "lecturer"]
TOPICS = {"demo1": "Why does the derivative of e^x equal itself?",
          "demo2": "How to spot a misleading chart or statistic: the tricks used to make numbers lie, and how to catch them"}
calls = Counter()
MARK = "<!-- generated tables below: rewritten on every run -->"


# ----------------------------------------------------------------------------- llm + cache
def cached(system, user, model, temperature, max_tokens=4000):
    key = hashlib.sha256(json.dumps([system, user, model, temperature, max_tokens]).encode()).hexdigest()[:24]
    f = CACHE / f"{key}.json"
    if f.exists():
        calls["cached"] += 1
        return json.loads(f.read_text())["text"]
    if calls["api"] >= MAX_CALLS:
        raise RuntimeError(f"call budget {MAX_CALLS} exhausted")
    calls["api"] += 1
    text = lm.llm(system, user, model=model, temperature=temperature, max_tokens=max_tokens)
    if not text.strip():
        raise RuntimeError(f"empty response from {model}")
    f.write_text(json.dumps({"model": model, "system": system, "user": user, "text": text}))
    return text


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def judge(system, user):
    """Single entry point for every judge call. Swap the backend via LM_JUDGE_PROVIDER."""
    provider = os.getenv("LM_JUDGE_PROVIDER", "anthropic")
    if provider != "anthropic":
        raise NotImplementedError(f"judge provider '{provider}' not implemented; add it here")
    return parse_json(cached(system + "\nRespond with JSON only.", user, JUDGE_MODEL, 0, 3000))


# ----------------------------------------------------------------------------- text prep
NAMES = re.compile(r"\bGrant\b|3Blue1Brown|3 ?blue ?1 ?brown|(Khan|Con) Academy|\bSal\b", re.I)

def clean(t):
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"[*_`]", "", t)
    return re.sub(r"\s+", " ", NAMES.sub("[name]", t)).strip()

def sentences(t):
    return [s for s in re.split(r"(?<=[.?!])\s+", t) if s]

def chunks(text, n):
    """Consecutive sentence-aligned chunks of >= n words (last short remainder dropped)."""
    out, cur = [], []
    for s in sentences(text):
        cur.append(s)
        if sum(len(x.split()) for x in cur) >= n:
            out.append(" ".join(cur)); cur = []
    return out

def window(text, n, rng):
    """A sentence-aligned window of >= n words starting at a random sentence."""
    ss = sentences(text)
    starts = [i for i in range(len(ss)) if sum(len(x.split()) for x in ss[i:]) >= n] or [0]
    i, out = rng.choice(starts), []
    while i < len(ss) and sum(len(x.split()) for x in out) < n:
        out.append(ss[i]); i += 1
    return " ".join(out)

PUNCT_SYS = ("Add sentence punctuation and capitalisation to this auto-caption transcript. Do not add, remove or "
             "change any word. Output only the text.")

def load_real():
    """Auto-captions with no punctuation (1 lecturer file) get punctuation only, so they are not a trivial tell."""
    real = {}
    for t in TEACHERS:
        real[t] = []
        for p in sorted((RUN2 / "data" / t).glob("*.txt")):
            txt = clean(p.read_text())
            if len(re.findall(r"[.?!]", txt)) < len(txt.split()) / 60:
                txt = clean(cached(PUNCT_SYS, txt, WRITER, 0, 8000))
            real[t].append({"src": p.stem, "text": txt})
    return real

def load_generated():
    gen = {}
    for t in TEACHERS:
        gen[f"demo2/{t}"] = {"teacher": t, "topic": "demo2",
                             "text": clean((RUN2 / "runs/demo2/scripts" / f"{t}.md").read_text())}
        beats = json.loads((RUN2 / "runs/demo1/scripts" / f"{t}_beats.json").read_text())
        gen[f"demo1/{t}"] = {"teacher": t, "topic": "demo1",
                             "text": clean(" ".join(b["text"] for b in sorted(beats, key=lambda b: b["i"])))}
    return gen

def make_unstyled():
    out = {}
    for k, topic in TOPICS.items():
        txt = cached("You write educational video scripts.",
                     f"Write a clear 5-minute explainer script on: {topic}\n"
                     "Output only the words to be spoken, as plain prose paragraphs, no headings or stage directions.",
                     WRITER, 0.7)
        out[f"unstyled/{k}"] = {"teacher": None, "topic": k, "text": clean(txt)}
    return out


# ----------------------------------------------------------------------------- tests 1-3: attribution
ATTR_SYS = ("You are an expert in authorship and teaching-style attribution. Judge by voice: sentence rhythm and "
            "length, person and address, hedges, verbal habits, how ideas are introduced and sequenced. "
            "Ignore subject matter: the anonymous text may be on a topic neither teacher covered.")

def attribution_trial(pool, anon, rng, exclude_src=None):
    """pool[teacher] = list of (src, 250-word chunk). Returns (picked_teacher, confidence, reason)."""
    labels = dict(zip(["X", "Y"], rng.sample(TEACHERS, 2)))
    blocks = []
    for lab, t in labels.items():
        ex = rng.sample([c for c in pool[t] if c[0] != exclude_src], 3)
        blocks.append(f"=== Teacher {lab} ===\n" + "\n\n".join(f"[excerpt {i+1}] {c[1]}" for i, c in enumerate(ex)))
    user = ("\n\n".join(blocks) + f"\n\n=== Anonymous text ===\n{anon}\n\n"
            'Whose teaching style does the anonymous text match? Return {"answer":"X" or "Y",'
            '"confidence":50-100 (50 = coin flip),"reason":"one sentence"}')
    r = judge(ATTR_SYS, user)
    return labels[r["answer"].strip().upper()[:1]], float(r.get("confidence", 50)), r.get("reason", "")

def run_attribution(texts, pool, real):
    rows = []
    for name, g in texts.items():
        for i in range(N_ATTR):
            rng = random.Random(f"{SEED}-attr-{name}-{i}")
            picked, conf, why = attribution_trial(pool, g["text"], rng)
            rows.append({"text": name, "true": g["teacher"], "picked": picked, "conf": conf, "reason": why})
    return rows

def run_ceiling(pool, real):
    rows = []
    for t in TEACHERS:
        for i in range(N_CEIL):
            rng = random.Random(f"{SEED}-ceil-{t}-{i}")
            doc = rng.choice(real[t])
            anon = window(doc["text"], 500, rng)
            picked, conf, why = attribution_trial(pool, anon, rng, exclude_src=doc["src"])
            rows.append({"text": f"real/{t}/{doc['src']}", "true": t, "picked": picked, "conf": conf, "reason": why})
    return rows


# ----------------------------------------------------------------------------- test 4: real vs generated
CLEAN_SYS = ("Lightly copy-edit this spoken transcript: remove filler words (um, uh, you know, kind of as filler), "
             "false starts and accidental word repetitions, and fix obvious transcription glitches. Change nothing "
             "else: keep every sentence, word choice and order. Output only the edited text.")
PAIR_SYS = ("You are an expert at telling human-produced teaching from AI-written imitations. Exactly one of two "
            "passages is a verbatim transcript of a real human teacher's video; the other was written by an AI "
            "imitating that teacher.")

def run_pairs(texts, real, n, tag):
    rows = []
    for name, g in texts.items():
        teachers = [g["teacher"]] if g["teacher"] else TEACHERS
        for t in teachers:
            for i in range(n):
                rng = random.Random(f"{SEED}-pair-{tag}-{name}-{t}-{i}")
                gen = window(g["text"], 300, rng)
                realc = window(rng.choice(real[t])["text"], len(gen.split()), rng)
                for variant in ("raw", "cleaned"):
                    if variant == "cleaned" and tag != "styled":
                        continue
                    r_txt = clean(cached(CLEAN_SYS, realc, WRITER, 0)) if variant == "cleaned" else realc
                    gen_first = rng.random() < 0.5 if variant == "raw" else not rows[-1]["gen_first"]
                    a, b = (gen, r_txt) if gen_first else (r_txt, gen)
                    r = judge(PAIR_SYS, f"=== Passage A ===\n{a}\n\n=== Passage B ===\n{b}\n\n"
                              'Which passage is the real human transcript? Return {"real":"A" or "B",'
                              '"confidence":50-100,"reason":"one sentence"}')
                    picked_gen = (r["real"].strip().upper()[:1] == "A") == gen_first
                    rows.append({"text": name, "teacher": t, "variant": variant, "gen_first": gen_first,
                                 "picked_generated": picked_gen, "conf": float(r.get("confidence", 50)),
                                 "reason": r.get("reason", ""), "words": [len(gen.split()), len(r_txt.split())]})
    return rows


# ----------------------------------------------------------------------------- test 5: beat structure
def segment(text, label):
    """Same system/user prompt as learnmorph.stage_grammar's segmentation step."""
    tax = json.dumps(lm.BEAT_TAXONOMY, indent=1)
    out = cached(
        f"You segment teaching transcripts into pedagogical beats.\nBeat taxonomy:\n{tax}\n"
        "Every span of the transcript maps to exactly one beat. If a recurring pattern fits nothing, "
        "add a new label and include 'proposed_new_label': true with a reason."
        "\nRespond with valid JSON only. No prose, no markdown fences.",
        f"Transcript ({label}):\n\n{text[:60000]}\n\n"
        'Return {"beats":[{"beat":label,"start_quote":first 8 words,"summary":one line,'
        '"devices":[signature devices seen: rhetorical question, second person, named character, '
        'callback, self-correction, pause word, joke, etc]}]}', WRITER, 0.2, 8000)
    return [b["beat"] for b in parse_json(out)["beats"]]

def dist(seqs, bigram):
    c = Counter()
    for s in seqs:
        c.update(zip(s, s[1:]) if bigram else s)
    n = sum(c.values()) or 1
    return {k: v / n for k, v in c.items()}

def cosine(p, q):
    keys = set(p) | set(q)
    dot = sum(p.get(k, 0) * q.get(k, 0) for k in keys)
    return dot / (math.sqrt(sum(v * v for v in p.values())) * math.sqrt(sum(v * v for v in q.values())) or 1)

def jsd(p, q):
    keys = set(p) | set(q); m = {k: (p.get(k, 0) + q.get(k, 0)) / 2 for k in keys}
    kl = lambda a: sum(a[k] * math.log2(a[k] / m[k]) for k in keys if a.get(k, 0) > 0)
    return (kl(p) + kl(q)) / 2

def run_structure(real, texts):
    real_seqs = {t: {d["src"]: segment(d["text"], d["src"]) for d in real[t]} for t in TEACHERS}
    gen_seqs = {n: segment(g["text"], n) for n, g in texts.items()}
    res = {"sequences": {"real": real_seqs, "generated": gen_seqs}, "compare": {}, "loo_real": {}}

    def comp(seqs, ref_by_teacher):
        row = {}
        for kind, bg in (("freq", False), ("bigram", True)):
            p = dist(seqs, bg)
            for t, refs in ref_by_teacher.items():
                q = dist(refs, bg)
                row[f"{kind}_cos_{t}"], row[f"{kind}_jsd_{t}"] = round(cosine(p, q), 3), round(jsd(p, q), 3)
        return row

    pooled = {t: list(real_seqs[t].values()) for t in TEACHERS}
    for n, s in gen_seqs.items():
        res["compare"][n] = comp([s], pooled)
    for t in TEACHERS:  # leave-one-out: real transcript vs the OTHER real transcripts = what "close" looks like
        for src, s in real_seqs[t].items():
            refs = {u: [x for k, x in real_seqs[u].items() if k != src] for u in TEACHERS}
            res["loo_real"][f"{t}/{src}"] = comp([s], refs)
    stored = {t: json.loads((RUN2 / "runs/demo2/profiles" / t / "move_grammar.json").read_text())["beat_frequency"]
              for t in TEACHERS}
    res["stored_grammar_vs_resegmented_freq_cos"] = {t: round(cosine(stored[t], dist(pooled[t], False)), 3)
                                                     for t in TEACHERS}
    return res


# ----------------------------------------------------------------------------- stats + report
def binom_p(k, n):  # one-sided P(X >= k) under p = 0.5
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n

def summarize_attr(rows):
    out = {}
    for name in dict.fromkeys(r["text"] if not r["text"].startswith("real/") else "real/" + r["true"] for r in rows):
        rs = [r for r in rows if r["text"] == name or (name.startswith("real/") and r["text"].startswith(name + "/"))]
        n, mc = len(rs), round(sum(r["conf"] for r in rs) / len(rs), 1)
        if rs[0]["true"]:
            k = sum(r["picked"] == r["true"] for r in rs)
            out[name] = {"correct": k, "n": n, "acc": k / n, "p_one_sided": round(binom_p(k, n), 4), "mean_conf": mc}
        else:
            k = sum(r["picked"] == "3b1b" for r in rs)
            out[name] = {"picked_3b1b": k, "n": n, "mean_conf": mc}
    return out

def summarize_pairs(rows):
    out = {}
    for key in dict.fromkeys((r["text"], r["variant"]) for r in rows):
        rs = [r for r in rows if (r["text"], r["variant"]) == key]
        k = sum(r["picked_generated"] for r in rs)
        out[f"{key[0]} [{key[1]}]"] = {"generated_picked_as_real": k, "n": len(rs), "rate": round(k / len(rs), 2),
                                       "mean_conf": round(sum(r["conf"] for r in rs) / len(rs), 1)}
    return out

def table(d):
    if not d:
        return "_no rows_\n"
    cols = list(next(iter(d.values())).keys())
    lines = ["| item | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    lines += [f"| {k} | " + " | ".join(str(round(v, 3) if isinstance(v, float) else v) for v in r.values()) + " |"
              for k, r in d.items()]
    return "\n".join(lines) + "\n"

def main():
    real, gen = load_real(), load_generated()
    pool = {t: [(d["src"], c) for d in real[t] for c in chunks(d["text"], 250)] for t in TEACHERS}
    results, errors = {"calls": None, "pool_sizes": {t: len(pool[t]) for t in TEACHERS}}, {}
    steps = [("unstyled_texts", make_unstyled),
             ("t1_attribution", lambda: run_attribution(gen, pool, real)),
             ("t2_ceiling", lambda: run_ceiling(pool, real)),
             ("t3_unstyled", lambda: run_attribution(results["unstyled_texts"], pool, real)),
             ("t4_pairs", lambda: run_pairs(gen, real, N_PAIR, "styled")),
             ("t4_pairs_unstyled", lambda: run_pairs(results["unstyled_texts"], real, N_PAIR_UNSTYLED, "unstyled")),
             ("t5_structure", lambda: run_structure(real, {**gen, **results["unstyled_texts"]}))]
    for name, fn in steps:
        try:
            results[name] = fn()
        except Exception as e:  # report, never estimate
            errors[name] = repr(e); print(f"[{name}] FAILED: {e!r}")
            if name == "unstyled_texts":
                results[name] = {}
    results["summary"] = {
        "t1": summarize_attr(results.get("t1_attribution", [])),
        "t2": summarize_attr(results.get("t2_ceiling", [])),
        "t3": summarize_attr(results.get("t3_unstyled", [])),
        "t4": summarize_pairs(results.get("t4_pairs", []) + results.get("t4_pairs_unstyled", [])),
    }
    results["errors"], results["calls"] = errors, dict(calls)
    (HERE / "results.json").write_text(json.dumps(results, indent=1))
    s5 = results.get("t5_structure", {})
    md = ["# LearnMorph style eval — raw tables\n", f"API calls this run: {dict(calls)}. Errors: {errors or 'none'}\n",
          "## Test 1 — recipe-free attribution (generated scripts)\n", table(results["summary"]["t1"]),
          "## Test 2 — ceiling (held-out real chunk, other video)\n", table(results["summary"]["t2"]),
          "## Test 3 — unstyled control (how often judged as 3b1b)\n", table(results["summary"]["t3"]),
          "## Test 4 — real vs generated (rate = generated picked as the real human; 0.5 = indistinguishable)\n",
          table(results["summary"]["t4"]),
          "## Test 5 — beat structure (cos: higher = closer; jsd: lower = closer)\n", table(s5.get("compare", {})),
          "### Leave-one-out real transcripts (what a real match looks like)\n", table(s5.get("loo_real", {})),
          f"Stored grammar beat_frequency vs fresh re-segmentation (cosine): "
          f"{s5.get('stored_grammar_vs_resegmented_freq_cos')}\n"]
    rp = HERE / "report.md"  # hand-written interpretation above the marker is kept; tables below are regenerated
    head = rp.read_text().split(MARK)[0] if rp.exists() and MARK in rp.read_text() else ""
    rp.write_text(head + MARK + "\n" + "\n".join(md))
    print("\n".join(md))

if __name__ == "__main__":
    main()
