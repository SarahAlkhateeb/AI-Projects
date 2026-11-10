"""
LearnMorph style evaluation: does a generated lesson sound like the REAL teacher? No grammar is ever shown to the judge.

Tests
  traits  coded speech traits and habit rates vs the real transcripts (no model; primary)
  1  attribution   judge sees real excerpts of teacher X and Y, then a generated script: whose style?
  2  ceiling       same, but the anonymous text is a real chunk from a video not among the excerpts
  3  unstyled      plain explainer with no style info (--unstyled), run through test 1: shows judge bias
  4  real-vs-gen   which of two ~300-word chunks is the real transcript? (--clean-variant: real chunk de-fillered)
  5  structure     segment into beats (learnmorph's taxonomy/prompt), compare beat frequencies (no judge)

Usage
  ANTHROPIC_API_KEY=... python eval_style.py --data data --script D3=3b1b=runs/D/scripts/3b1b.md \
      --script DL=lecturer=runs/D/scripts/lecturer.md --tests traits,1,3,5,4 --t4-teachers lecturer \
      --heldout lecturer=N2PpRnFqnqY --unstyled demo2="How to spot a misleading chart" --out results.json
  --data holds one folder per teacher with *.txt transcripts. Scripts may be .md or *_beats.json.
  Every response is cached (--cache, default ./eval_cache), so reruns are free. LM_JUDGE_PROVIDER picks the judge.
"""
import argparse, hashlib, json, math, os, random, re, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learnmorph as lm  # raw-urllib llm() and BEAT_TAXONOMY
import style_traits as st

WRITER, JUDGE_MODEL = "claude-sonnet-5-5", os.getenv("LM_EVAL_JUDGE_MODEL", "claude-opus-5-5")
SEED = 1234
calls = Counter()
CFG = {"cache": Path("eval_cache"), "max_calls": int(os.getenv("LM_MAX_CALLS", "200"))}


# ----------------------------------------------------------------------------- llm + cache
def cached(system, user, model, temperature, max_tokens=4000):
    key = hashlib.sha256(json.dumps([system, user, model, temperature, max_tokens]).encode()).hexdigest()[:24]
    f = CFG["cache"] / f"{key}.json"
    if f.exists():
        calls["cached"] += 1
        return json.loads(f.read_text())["text"]
    if calls["api"] >= CFG["max_calls"]:
        raise RuntimeError(f"call budget {CFG['max_calls']} exhausted")
    calls["api"] += 1
    text = lm.llm(system, user, model=model, temperature=temperature, max_tokens=max_tokens)
    if not text.strip():
        raise RuntimeError(f"empty response from {model}")
    CFG["cache"].mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"model": model, "system": system, "user": user, "text": text}))
    return text


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def judge(system, user):
    """Single entry point for every judge call. Add other providers here (LM_JUDGE_PROVIDER)."""
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
    out, cur = [], []
    for s in sentences(text):
        cur.append(s)
        if sum(len(x.split()) for x in cur) >= n:
            out.append(" ".join(cur)); cur = []
    return out

def window(text, n, rng):
    ss = sentences(text)
    starts = [i for i in range(len(ss)) if sum(len(x.split()) for x in ss[i:]) >= n] or [0]
    i, out = rng.choice(starts), []
    while i < len(ss) and sum(len(x.split()) for x in out) < n:
        out.append(ss[i]); i += 1
    return " ".join(out)

PUNCT_SYS = ("Add sentence punctuation and capitalisation to this auto-caption transcript. Do not add, remove or "
             "change any word. Output only the text.")

def load_real(data):
    """Auto-captions with no punctuation get punctuation only (one model call), so they are not a trivial tell."""
    real = {}
    for tdir in sorted(p for p in Path(data).iterdir() if p.is_dir()):
        real[tdir.name] = []
        for p in sorted(tdir.glob("*.txt")):
            txt = clean(p.read_text())
            if len(re.findall(r"[.?!]", txt)) < len(txt.split()) / 60:
                txt = clean(cached(PUNCT_SYS, txt, WRITER, 0, 8000))
            real[tdir.name].append({"src": p.stem, "text": txt, "path": str(p)})
    return real

def load_script(path):
    p = Path(path)
    if p.suffix == ".json":
        return clean(" ".join(b["text"] for b in sorted(json.loads(p.read_text()), key=lambda b: b["i"])))
    return clean(p.read_text())

def make_unstyled(topics):
    out = {}
    for k, topic in topics.items():
        txt = cached("You write educational video scripts.",
                     f"Write a clear 5-minute explainer script on: {topic}\n"
                     "Output only the words to be spoken, as plain prose paragraphs, no headings or stage directions.",
                     WRITER, 0.7)
        out[f"unstyled/{k}"] = {"teacher": None, "text": clean(txt)}
    return out


# ----------------------------------------------------------------------------- tests 1-3: attribution
ATTR_SYS = ("You are an expert in authorship and teaching-style attribution. Judge by voice: sentence rhythm and "
            "length, person and address, hedges, verbal habits, how ideas are introduced and sequenced. "
            "Ignore subject matter: the anonymous text may be on a topic neither teacher covered.")

def attribution_trial(pool, teachers, anon, rng, exclude_src=None):
    labels = dict(zip(["X", "Y"], rng.sample(teachers, 2)))
    blocks = []
    for lab, t in labels.items():
        ex = rng.sample([c for c in pool[t] if c[0] != exclude_src], 3)
        blocks.append(f"=== Teacher {lab} ===\n" + "\n\n".join(f"[excerpt {i+1}] {c[1]}" for i, c in enumerate(ex)))
    user = ("\n\n".join(blocks) + f"\n\n=== Anonymous text ===\n{anon}\n\n"
            'Whose teaching style does the anonymous text match? Return {"answer":"X" or "Y",'
            '"confidence":50-100 (50 = coin flip),"reason":"one sentence"}')
    r = judge(ATTR_SYS, user)
    return labels[r["answer"].strip().upper()[:1]], float(r.get("confidence", 50)), r.get("reason", "")

def run_attribution(texts, pool, teachers, n):
    rows = []
    for name, g in texts.items():
        for i in range(n):
            rng = random.Random(f"{SEED}-attr-{name}-{i}")
            picked, conf, why = attribution_trial(pool, teachers, g["text"], rng)
            rows.append({"text": name, "true": g["teacher"], "picked": picked, "conf": conf, "reason": why})
    return rows

def run_ceiling(pool, real, teachers, n):
    rows = []
    for t in teachers:
        for i in range(n):
            rng = random.Random(f"{SEED}-ceil-{t}-{i}")
            doc = rng.choice(real[t])
            picked, conf, why = attribution_trial(pool, teachers, window(doc["text"], 500, rng), rng, doc["src"])
            rows.append({"text": f"real/{t}", "true": t, "picked": picked, "conf": conf, "reason": why})
    return rows


# ----------------------------------------------------------------------------- test 4: real vs generated
CLEAN_SYS = ("Lightly copy-edit this spoken transcript: remove filler words (um, uh, you know, kind of as filler), "
             "false starts and accidental word repetitions, and fix obvious transcription glitches. Change nothing "
             "else: keep every sentence, word choice and order. Output only the edited text.")
PAIR_SYS = ("You are an expert at telling human-produced teaching from AI-written imitations. Exactly one of two "
            "passages is a verbatim transcript of a real human teacher's video; the other was written by an AI "
            "imitating that teacher.")

def run_pairs(texts, real, heldout, n, seed_tag, cleaned, only):
    """Real chunks come only from the held-out transcript when one is given for that teacher."""
    rows = []
    for name, g in texts.items():
        if not g["teacher"] or (only and g["teacher"] not in only):
            continue
        docs = [d for d in real[g["teacher"]] if d["src"] == heldout.get(g["teacher"])] or real[g["teacher"]]
        for i in range(n):
            rng = random.Random(f"{seed_tag}-{name}-{i}")
            gen = window(g["text"], 300, rng)
            realc = window(rng.choice(docs)["text"] if len(docs) > 1 else docs[0]["text"], len(gen.split()), rng)
            gen_first = rng.random() < 0.5
            for variant in ("raw", "cleaned") if cleaned else ("raw",):
                r_txt = realc if variant == "raw" else clean(cached(
                    CLEAN_SYS + " Also fix capitalisation and mis-transcribed names.", realc, WRITER, 0))
                a, b = (gen, r_txt) if gen_first else (r_txt, gen)
                r = judge(PAIR_SYS, f"=== Passage A ===\n{a}\n\n=== Passage B ===\n{b}\n\n"
                          'Which passage is the real human transcript? Return {"real":"A" or "B",'
                          '"confidence":50-100,"reason":"one sentence"}')
                rows.append({"text": name, "variant": variant,
                             "picked_generated": (r["real"].strip().upper()[:1] == "A") == gen_first,
                             "conf": float(r.get("confidence", 50)), "reason": r.get("reason", "")})
    return rows


# ----------------------------------------------------------------------------- test 5: beat structure
def segment(text, label):
    """Same prompt as learnmorph.stage_grammar's segmentation step."""
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

def dist(seqs, bigram=False):
    c = Counter()
    for s in seqs:
        c.update(zip(s, s[1:]) if bigram else s)
    n = sum(c.values()) or 1
    return {k: v / n for k, v in c.items()}

def cosine(p, q):
    dot = sum(p.get(k, 0) * q.get(k, 0) for k in set(p) | set(q))
    return dot / (math.sqrt(sum(v * v for v in p.values())) * math.sqrt(sum(v * v for v in q.values())) or 1)

def jsd(p, q):
    keys = set(p) | set(q); m = {k: (p.get(k, 0) + q.get(k, 0)) / 2 for k in keys}
    kl = lambda a: sum(a[k] * math.log2(a[k] / m[k]) for k in keys if a.get(k, 0) > 0)
    return (kl(p) + kl(q)) / 2

def run_structure(texts, real, teachers):
    pooled = {t: [segment(d["text"], d["src"]) for d in real[t]] for t in teachers}
    out = {}
    for name, g in texts.items():
        p = dist([segment(g["text"], name)])
        out[name] = {}
        for t in teachers:
            q = dist(pooled[t])
            out[name][f"cos_{t}"], out[name][f"jsd_{t}"] = round(cosine(p, q), 3), round(jsd(p, q), 3)
    return out


# ----------------------------------------------------------------------------- coded traits (no model)
def run_traits(texts, data, heldout):
    real = {t.name: st.load_texts(t.glob("*.txt")) for t in sorted(Path(data).iterdir()) if t.is_dir()}
    ref = {}
    for t, docs in real.items():
        punct = [d for d in docs if st.is_punctuated(d["text"])]
        body = " ".join(d["text"] for d in punct)
        ref[t] = {"traits": st.speech_traits(body), "per_1000w": st.per_k(body), "band": st.sentence_band(punct),
                  "heldout": heldout.get(t)}
    out = {"real": {t: {"sentence_len_mean": r["traits"]["sentence_len_mean"], **r["traits"], **r["per_1000w"],
                        "band": [r["band"]["lo"], r["band"]["hi"]]} for t, r in ref.items()}, "generated": {}}
    for name, g in texts.items():
        if not g["teacher"]:
            continue
        r, tr, pk = ref[g["teacher"]], st.speech_traits(g["text"]), st.per_k(g["text"])
        out["generated"][name] = {
            "words": len(g["text"].split()), **tr, **pk,
            "in_sentence_band": st.band_check(g["text"], r["band"])[0],
            "trait_distance": st.trait_distance(tr, r["traits"]),
            "habits_over_1.5x_real": {k: round(v / max(r["per_1000w"][k], 0.25), 1) for k, v in pk.items()
                                      if v > 1.5 * max(r["per_1000w"][k], 0.25)}}
    return out


# ----------------------------------------------------------------------------- summaries + main
def binom_p(k, n):
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n

def summarize_attr(rows):
    out = {}
    for name in dict.fromkeys(r["text"] for r in rows):
        rs = [r for r in rows if r["text"] == name]
        mc = round(sum(r["conf"] for r in rs) / len(rs), 1)
        if rs[0]["true"]:
            k = sum(r["picked"] == r["true"] for r in rs)
            out[name] = {"correct": k, "n": len(rs), "p_one_sided": round(binom_p(k, len(rs)), 4), "mean_conf": mc}
        else:
            out[name] = {"picked": dict(Counter(r["picked"] for r in rs)), "n": len(rs), "mean_conf": mc}
    return out

def summarize_pairs(rows):
    out = {}
    for key in dict.fromkeys((r["text"], r["variant"]) for r in rows):
        rs = [r for r in rows if (r["text"], r["variant"]) == key]
        out[f"{key[0]} [{key[1]}]"] = {"generated_picked_as_real": sum(r["picked_generated"] for r in rs),
                                       "n": len(rs), "mean_conf": round(sum(r["conf"] for r in rs) / len(rs), 1)}
    return out

def kv(s):
    k, _, v = s.partition("=")
    return k, v

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=os.getenv("LM_DATA_DIR", "data"))
    ap.add_argument("--script", action="append", default=[], help="NAME=TEACHER=PATH")
    ap.add_argument("--unstyled", action="append", default=[], help="KEY=TOPIC (test 3 control)")
    ap.add_argument("--tests", default="traits,1,2,3,4,5")
    ap.add_argument("--heldout", action="append", default=[], help="TEACHER=SOURCE_STEM (test 4 real chunks)")
    ap.add_argument("--t4-teachers", default="", help="comma list; default all")
    ap.add_argument("--clean-variant", action="store_true")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--pairs", type=int, default=5)
    ap.add_argument("--seed-tag", default="gen2-t4")
    ap.add_argument("--cache", default=os.getenv("LM_EVAL_CACHE", "eval_cache"))
    ap.add_argument("--max-calls", type=int, default=CFG["max_calls"])
    ap.add_argument("--out", default="eval_results.json")
    a = ap.parse_args()
    CFG.update(cache=Path(a.cache), max_calls=a.max_calls)
    tests = set(a.tests.split(","))
    heldout = dict(kv(h) for h in a.heldout)
    texts = {}
    for s in a.script:
        name, teacher, path = s.split("=", 2)
        texts[name] = {"teacher": teacher, "text": load_script(path)}
    res, errors = {"scripts": {k: v["teacher"] for k, v in texts.items()}}, {}
    if "traits" in tests:
        res["traits"] = run_traits(texts, a.data, heldout)
    real = load_real(a.data) if tests - {"traits"} else {}
    teachers = sorted(real)
    pool = {t: [(d["src"], c) for d in real[t] for c in chunks(d["text"], 250)] for t in teachers}
    steps = [("t1", "1", lambda: summarize_attr(run_attribution(texts, pool, teachers, a.trials))),
             ("t2", "2", lambda: summarize_attr(run_ceiling(pool, real, teachers, a.trials))),
             ("t3", "3", lambda: summarize_attr(run_attribution(
                 make_unstyled(dict(kv(u) for u in a.unstyled)), pool, teachers, a.trials))),
             ("t4", "4", lambda: summarize_pairs(run_pairs(
                 texts, real, heldout, a.pairs, a.seed_tag, a.clean_variant, set(filter(None, a.t4_teachers.split(",")))))),
             ("t5", "5", lambda: run_structure(texts, real, teachers))]
    for key, t, fn in steps:
        if t in tests:
            try:
                res[key] = fn()
            except Exception as e:  # report, never estimate
                errors[key] = repr(e); print(f"[{key}] FAILED: {e!r}")
    res["errors"], res["calls"] = errors, dict(calls)
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "traits"}, indent=1))


if __name__ == "__main__":
    main()
