"""Measurable style traits computed in code (no model): sentence length, fillers, hedges, restarts,
sentence openers, conjunction joining, and per-1,000-word rates of countable habits and structural devices."""
import re
from pathlib import Path

NAMES = re.compile(r"\bGrant\b|3Blue1Brown|(Khan|Con) Academy|\bSal\b", re.I)
FILLERS = r"\b(um+|uh+|you know|kind of|sort of|i mean)\b"
HEDGES = r"\b(maybe|probably|roughly|i think|in a sense|pretty much|essentially|basically|let'?s say)\b"
RESTARTS = r"--|—|\s–\s|\b(\w+) \1\b|\b(actually|or rather|well, actually|sorry)\b"
STARTERS = ["so", "now", "and", "okay", "but", "well"]
JOINERS = {"comma_joined_clauses": r", (and|but|so|which)\b", "and_total": r"\band\b"}
# Countable habits and structural devices. All are capped by the habit budget (rate per 1,000 words).
DEVICES = {
    "rhetorical_question": r"\?",
    "dash_self_interruption": r"--|—|\s–\s",
    "colour_or_pen_talk": r"\b(colou?r|marker|pen)\b",
    "let_me": r"\blet me\b",
    "lets_say": r"\blet'?s say\b",
    "right_tag": r"\bright\?",
    "nothing_special": r"\bnothing special\b",
    "imagine_or_picture": r"\b(imagine|picture)\b",
    "by_the_way": r"\bby the way\b",
    "remember_callback": r"\bremember\b",
    # structural (plan-level) devices
    "signpost_preview": r"\b(coming up|up next|next video|in the next|we'll see|by the end of this|later on|later in)\b",
    "recap_summary": r"\b(to recap|let's recap|in summary|to summari[sz]e|so far,? we|let's review|recap|takeaway|key idea|in short)\b",
    "coined_label": r"\b(i'll call|let's call|we'll call|we call (this|it)|call (this|it|that) (a|an|the)|what i call)\b",
    "enumerated_list": r"\b(first|second|third|firstly|secondly|number one|number two|step one|step two)\b[,:]",
}
STRUCTURAL = ["signpost_preview", "recap_summary", "coined_label", "enumerated_list"]
# Planning language that asks for those devices (counted in plan goals/examples).
PLAN_TIDY = (r"\b(recap\w*|summar\w*|preview\w*|coming up|up next|takeaway\w*|checklist|rule of thumb|slogan|"
             r"(call|name|label|dub) (it|this|the)|named? (test|rule|heuristic|trick)|"
             r"(two|three|four|five) (questions|rules|checks|tricks|steps|things))\b")


def norm(t):
    t = t.replace("’", "'").replace("‘", "'")
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    return re.sub(r"\s+", " ", NAMES.sub("[name]", re.sub(r"[*_`]", "", t))).strip()


def sentences(t):
    return [s for s in re.split(r"(?<=[.?!])\s+", t) if s.strip()]


def is_punctuated(t):
    """Auto-captions without punctuation can't give sentence statistics."""
    return len(re.findall(r"[.?!]", t)) >= len(t.split()) / 60


def load_texts(paths):
    return [{"src": Path(p).stem, "text": norm(Path(p).read_text())} for p in sorted(paths)]


def rates(text, patterns, per=1000):
    t, n = norm(text).lower(), max(len(text.split()), 1)
    return {k: round(len(re.findall(p, t)) * per / n, 2) for k, p in patterns.items()}


def device_counts(text):
    t = norm(text).lower()
    return {k: len(re.findall(p, t)) for k, p in DEVICES.items()}


def per_k(text):
    return rates(text, DEVICES)


def sent_mean(text):
    lens = [len(s.split()) for s in sentences(norm(text))]
    return round(sum(lens) / max(len(lens), 1), 1)


def speech_traits(text):
    t = norm(text)
    low, n = t.lower(), max(len(t.split()), 1)
    lens = sorted(len(s.split()) for s in sentences(t)) or [0]
    q = lambda f: lens[min(len(lens) - 1, int(f * len(lens)))]
    starts = [s.split()[0].lower().strip(",.") for s in sentences(t) if s.split()]
    return {
        "sentence_len_mean": round(sum(lens) / len(lens), 1),
        "sentence_len_p10_p50_p90": [q(.1), q(.5), q(.9)],
        "share_sentences_under_8_words": round(sum(l < 8 for l in lens) / len(lens), 2),
        "share_sentences_over_30_words": round(sum(l > 30 for l in lens) / len(lens), 2),
        "fillers_per_100w": round(100 * len(re.findall(FILLERS, low)) / n, 2),
        "hedges_per_100w": round(100 * len(re.findall(HEDGES, low)) / n, 2),
        "restarts_self_corrections_per_100w": round(100 * len(re.findall(RESTARTS, low)) / n, 2),
        "sentence_start_share": {w: round(starts.count(w) / max(len(starts), 1), 2) for w in STARTERS},
        **rates(text, JOINERS),
    }


def sentence_band(texts, widen=0.15):
    """Band for mean sentence length: [min, max] of per-transcript means, widened by 15% each side.
    Joiner limits: 1.5x the highest per-transcript rate. Unpunctuated transcripts are skipped."""
    ok = [d["text"] for d in texts if is_punctuated(d["text"])]
    means = [sent_mean(t) for t in ok]
    joins = [rates(t, JOINERS) for t in ok]
    return {"per_transcript_means": means,
            "lo": round(min(means) * (1 - widen), 1), "hi": round(max(means) * (1 + widen), 1),
            "joiner_max": {k: round(1.5 * max(j[k] for j in joins), 1) for k in JOINERS}}


def band_check(text, band):
    """Returns (ok, distance, message). distance = 0 inside the band."""
    m, j = sent_mean(text), rates(text, JOINERS)
    d = max(band["lo"] - m, m - band["hi"], 0) / band["lo"]
    over = {k: v for k, v in j.items() if v > band["joiner_max"][k]}
    d += sum((v - band["joiner_max"][k]) / band["joiner_max"][k] for k, v in over.items())
    msg = f"mean sentence length {m} (target {band['lo']}-{band['hi']})"
    if over:
        msg += "; too many joined clauses " + ", ".join(f"{k} {v}/1000w (max {band['joiner_max'][k]})" for k, v in over.items())
    return d == 0, round(d, 3), msg


def trait_distance(gen, real):
    """Mean relative gap over scalar traits + sentence-opener shares (0 = identical)."""
    keys = ["sentence_len_mean", "share_sentences_under_8_words", "share_sentences_over_30_words",
            "fillers_per_100w", "hedges_per_100w", "restarts_self_corrections_per_100w"]
    gaps = [abs(gen[k] - real[k]) / max(abs(real[k]), 0.05) for k in keys]
    gaps += [abs(gen["sentence_start_share"][w] - real["sentence_start_share"][w])
             / max(real["sentence_start_share"][w], 0.05) for w in STARTERS]
    return round(sum(min(g, 3) for g in gaps) / len(gaps), 2)


if __name__ == "__main__":  # python style_traits.py transcript.txt [...]: print traits for each file
    import json, sys
    for p in sys.argv[1:]:
        t = Path(p).read_text()
        print(p, json.dumps({**speech_traits(t), **per_k(t)}))
