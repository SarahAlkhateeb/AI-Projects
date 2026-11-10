"""
OPTIONAL — NOT RUN (Hugging Face is blocked in the eval container). Untested code.

LUAR authorship-embedding similarity (Rivera-Soto et al., "Learning Universal Authorship
Representations", EMNLP 2021). Model id and input layout follow the model card at
https://huggingface.co/rrivera1849/LUAR-MUD : inputs are (batch, episode_length, max_tokens),
output is one 512-d vector per episode; trust_remote_code is needed for the custom model class.

Each "episode" = several ~100-word chunks of one text. Reports cosine similarity of:
  generated vs real same teacher, generated vs real other teacher,
  ceiling = real vs real same teacher (different videos), floor = real 3b1b vs real lecturer.
Usage (machine with HF access): pip install torch transformers; ANTHROPIC_API_KEY must be set (any value)
because eval_style imports learnmorph, which checks it; no API calls are made.  python luar_score.py
"""
import itertools, json, sys
from pathlib import Path
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from eval_style import TEACHERS, clean, load_generated  # load_real may need the API for punctuation

MODEL, EPISODE, MAX_TOK = "rrivera1849/LUAR-MUD", 8, 128
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True).eval()


def embed(text):
    words = text.split()
    pieces = [" ".join(words[i:i + 100]) for i in range(0, len(words), 100)][:EPISODE]
    pieces += [pieces[-1]] * (EPISODE - len(pieces))  # pad to a fixed episode length
    t = tok(pieces, max_length=MAX_TOK, padding="max_length", truncation=True, return_tensors="pt")
    with torch.inference_mode():
        out = model(input_ids=t["input_ids"].reshape(1, EPISODE, -1),
                    attention_mask=t["attention_mask"].reshape(1, EPISODE, -1))
    return F.normalize(out, dim=-1)[0]


real = {t: {p.stem: embed(clean(p.read_text())) for p in Path(f"/home/claude/run2/data/{t}").glob("*.txt")}
        for t in TEACHERS}
gen = {k: embed(v["text"]) for k, v in load_generated().items()}
cos = lambda a, b: round(float(a @ b), 3)
res = {"generated": {}, "ceiling_same_teacher": {}, "floor_cross_teacher": None}
for k, e in gen.items():
    own = k.split("/")[1]
    other = [t for t in TEACHERS if t != own][0]
    res["generated"][k] = {f"vs_real_{own}": round(sum(cos(e, r) for r in real[own].values()) / len(real[own]), 3),
                           f"vs_real_{other}": round(sum(cos(e, r) for r in real[other].values()) / len(real[other]), 3)}
for t in TEACHERS:
    pairs = list(itertools.combinations(real[t].values(), 2))
    res["ceiling_same_teacher"][t] = round(sum(cos(a, b) for a, b in pairs) / len(pairs), 3)
cross = [cos(a, b) for a in real["3b1b"].values() for b in real["lecturer"].values()]
res["floor_cross_teacher"] = round(sum(cross) / len(cross), 3)
print(json.dumps(res, indent=1))
Path(__file__).with_name("luar_results.json").write_text(json.dumps(res, indent=1))
