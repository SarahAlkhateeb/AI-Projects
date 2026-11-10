# AI Projects

Applied AI projects, one folder each. Every project carries its own README, a status page with measured
results, and a changelog.

| Project | What it does | Stack | Status |
|---|---|---|---|
| [LearnMorph](LearnMorph/) | Learns *how* a teacher teaches from their transcripts, then writes and animates a new lesson on a different topic in that teaching style. | Python, Claude API, Remotion (React), Kokoro TTS | Working prototype. Runs end to end; style fidelity is measured and not yet at target. See [status](LearnMorph/docs/STATUS.md). |

## How the projects are organised

- `README.md`: what the project is, how it works, how to run it.
- `docs/STATUS.md`: current state with numbers taken from committed run files, including what does not work yet.
- `docs/CHANGELOG.md`: dated history.
- `eval/`: evaluation code and reports, where a project has them.

Results are reported as measured, with the limitations of each measurement stated next to it.
