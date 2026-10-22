# Workflow runtime

`runner.py` coordinates a bounded Scout → Researcher → Writer pipeline, validates handoffs and checkpoints, builds in isolated workspaces, and publishes a version only after validation. An advisory post-build Correcter reports possible leads for a later run; it is read-only and non-blocking.

`scout_retrieval.py` provides deterministic literature search/download helpers. `nono_launcher.py` illustrates a Nono-isolated worker/build adapter. Provider names, profiles, models, paths, and credentials in this public copy are anonymized examples; configure them locally before use.

Per-run comments are shown to Scout and Researcher. Scout uses any stated research topic to focus its bounded source search; if comments are absent or contain no research topic, it uses the default plan. Comments are guidance, not evidence.

`tests/` contains offline synthetic fixtures. Run `./workflow test`; it makes no model calls or live literature searches. Never commit local manuscripts, run outputs, references, PDFs, credentials, or version archives.
