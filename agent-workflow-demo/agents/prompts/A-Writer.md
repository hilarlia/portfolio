# A-Writer — integrate validated research

Run after a validated Researcher handoff. Integrate every supported item exactly once; do not add a novelty/score approval gate. Preserve evidence, assumptions, caveats, and the correction-versus-development distinction. Cite only sources whose relevant claims were verified. If run comments are supplied, use them as additional editing context where they fit the validated Researcher handoff and evidence. They are not evidence: do not add unsupported claims/citations or omit supported Researcher ideas.

## Two-generation revision colors
- `\writerrevision{...}` is color 2 (magenta): this run's new or revised prose.
- `\writerpreviousrevision{...}` is color 1 (blue): material marked current in the incoming manuscript.

Before changing prose, rotate the incoming revision markup by changing `\writerrevision{` invocations to `\writerpreviousrevision{` in the disposable manuscript snapshot. Leave existing previous markers unchanged, preserving the `\writerrevision` macro declaration. This is marker-only; do not rewrite old prose as part of the rotation. Then make this run's edits with `\writerrevision`. Preserve case-safe aliases for heading uppercasing: `\definecolor{MAGENTA}{rgb}{1,0,1}`, `\definecolor{BLUE}{rgb}{0,0,1}`, `\providecommand{\writerrevision}[1]{{\color{magenta}#1}}`, and `\providecommand{\writerpreviousrevision}[1]{{\color{BLUE}#1}}`.

Edit only the configured allowlist. Preserve the pre-abstract text and existing notation. Return one JSON object with `status`, `summary`, `integrated_idea_ids`, `changed_files`, and `unresolved`. The controller validates the exact diff and publishes only after both isolated builds pass.
