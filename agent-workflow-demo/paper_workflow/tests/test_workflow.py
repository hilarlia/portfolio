from __future__ import annotations

import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_workflow import nono_launcher, runner, scout_retrieval


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="paper-workflow-test-")
        self.root = Path(self.temp.name)
        self.outputs = self.root / "Agent-Outputs"
        self.run_dir = self.outputs / "runs/test-run"
        (self.run_dir / "Paper/Work-In-Progress/LatexInclusion").mkdir(parents=True)
        (self.run_dir / "Paper/Manuscript-Style-Assets").mkdir(parents=True)
        (self.run_dir / "skills").mkdir()
        (self.run_dir / "Agent-Outputs/A-Scout/papers").mkdir(parents=True)
        main = ("% fixed preamble\n\\begin{document}\n\\begin{abstract}Baseline.\\end{abstract}\n"
                "\\section{Results}\nBaseline result.\n\\appendix\n\\section{Notation}\nKeep this notation.\n"
                "\\section{Proof}\nProof.\n\\end{document}\n")
        (self.run_dir / "Paper/Work-In-Progress/main.tex").write_text(main)
        (self.run_dir / "Paper/Work-In-Progress/main.pdf").write_bytes(b"%PDF-1.4 baseline")
        (self.run_dir / "source-main.tex").write_text(main)
        for relative in runner.WRITER_FILES[1:]:
            path = self.run_dir / "Paper" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("% synthetic manuscript fixture\n")
        for relative in runner.WRITER_FILES:
            target = self.run_dir / "source-writer-files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((self.run_dir / "Paper" / relative).read_bytes())
        (self.run_dir / "Paper/Manuscript-Style-Assets/notation.tex").write_text("% notation fixture\n")
        (self.run_dir / "skills/skills-paper_writing.md").write_text("synthetic skill")
        (self.run_dir / "skills/skills-paper_citation.md").write_text("synthetic skill")
        (self.run_dir / "skills/BetterBibTeX-preferences.json").write_text("{}")
        (self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json").write_text(
            '{"schema_version":1,"papers":[]}\n')
        for role, relative in runner.OUTPUT_FILES.items():
            if role != "A-Scout":
                runner.write_json(self.run_dir / relative, {"preflight_placeholder": True})
        (self.run_dir / "jobs").mkdir()
        (self.run_dir / "logs").mkdir()
        self.initial = runner.tree_manifest(self.run_dir / "Paper")
        runner.write_json(self.run_dir / "source.manifest.json", self.initial)
        self.paper_hash = runner.manifest_hash(self.initial)
        self.config = runner.load_config()

    def tearDown(self):
        self.temp.cleanup()

    def _envelope(self, role, round_number):
        job = runner._agent_job(self.config, "test-run", self.run_dir, role, round_number, self.paper_hash)
        return {key: job[key] for key in
                ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")}

    def _scout(self, run_dir, round_number=1, status="ok", count=5, download=True):
        envelope = self._envelope("A-Scout", round_number)
        papers = []
        for number in range(1, count + 1):
            paper_id = f"S{number}"
            path = None
            if download:
                path = f"Agent-Outputs/A-Scout/papers/{paper_id}.pdf"
                target = run_dir / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"%PDF-1.4 synthetic test fixture")
            papers.append({"id": paper_id, "title": f"Synthetic source {number}", "authors": "Test Author",
                           "year": "2025", "venue": "Synthetic venue", "url": f"https://example.org/{paper_id}",
                           "doi": f"10.0000/synthetic{number}", "locator": "Theorem 1",
                           "support": "Synthetic theorem statement.", "relevance": "A synthetic bottleneck.",
                           "transfer_limits": "Synthetic only.", "retrieved_at": "2026-10-18",
                           "download_path": path})
        return {**envelope, "status": status,
                "summary": "Synthetic source search.", "papers": papers,
                "techniques": [], "queries": [{"query": "synthetic topic", "outcome": "fixture only"}],
                "limitations": "Synthetic fixture; not scientific evidence."}

    def _researcher(self, round_number, run_dir):
        idea = {"id": "I1", "title": "A testable result", "kind": "correction",
                "target": "Results section", "source_context": "Current synthetic theorem at Results/line 1 with assumption A1.",
                "bottleneck": "A synthetic proof gap",
                "statement": "A precise synthetic statement.", "assumptions": ["Synthetic assumption"],
                "proof": "Complete synthetic derivation: assumption implies the stated identity by direct substitution.",
                "prior_work": ["S1"], "novelty_delta": "Correction, not a novelty claim.",
                "caveats": ["Synthetic only"], "narrative_role": "Connect the example to the theorem.",
                "paper_changes": ["Paper/Work-In-Progress/main.tex — Results section: Add the stated result and caveat."],
                "impact_map": [{"id": "M1", "file": "Paper/Work-In-Progress/main.tex",
                                "locator": "Results section", "linked_claim": "Synthetic baseline result",
                                "required_edit": "Add the stated result and caveat."}],
                "falsification_test": "Check the identity in the stated synthetic boundary case."}
        return {**self._envelope("A-Researcher", round_number), "status": "ok",
                "summary": "Synthetic proof and narrative.", "ideas": [idea],
                "narrative_plan": ["State the result", "Connect it to the example"],
                "papers_read": [{"id": f"S{i}", "summary": f"Synthetic source {i} summary.", "locator": "Theorem 1"}
                                for i in range(1, 6)],
                "prior_papers_reused": [], "no_idea_reason": ""}

    def _make_writer_build_failure(self):
        config = copy.deepcopy(self.config)
        config["paths"].update({"paper": "LivePaper", "outputs": "Agent-Outputs"})
        shutil.copytree(self.run_dir / "Paper", self.root / "LivePaper")
        scout = self._scout(self.run_dir)
        runner.write_json(self.run_dir / runner.OUTPUT_FILES["A-Scout"], scout)
        researcher_job = runner._agent_job(config, "test-run", self.run_dir, "A-Researcher", 1, self.paper_hash)
        runner.write_json(self.run_dir / "jobs/A-Researcher-r1.json", researcher_job, compact=True)
        researcher = self._researcher(1, self.run_dir)
        runner.write_json(self.run_dir / runner.OUTPUT_FILES["A-Researcher"], researcher)
        job = runner._agent_job(config, "test-run", self.run_dir, "A-Writer", 1, self.paper_hash)
        prompt = runner._prompt(config, "A-Writer", job, self.run_dir)
        runner.write_json(self.run_dir / "jobs/A-Writer-r1.json", job, compact=True)
        (self.run_dir / "jobs/A-Writer-r1.md").write_text(prompt, encoding="utf-8")
        main = self.run_dir / "Paper/Work-In-Progress/main.tex"
        main.write_text(main.read_text().replace("Baseline result.", r"\writerrevision{Integrated result.}"))
        writer = {**{key: job[key] for key in
                     ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")},
                  "status": "ok", "summary": "Integrated all Researcher ideas.",
                  "integrated_idea_ids": [idea["id"] for idea in researcher["ideas"]],
                  "changed_files": ["Work-In-Progress/main.tex"], "unresolved": []}
        runner.validate_envelope(writer, job)
        runner.validate_agent_payload("A-Writer", writer, self.run_dir, config)
        runner.validate_manuscript_invariants(self.run_dir / "Paper", ["Work-In-Progress/main.tex"])
        runner.write_json(self.run_dir / runner.OUTPUT_FILES["A-Writer"], writer)
        metrics = {"provider_cost_usd": 0.25, "cost_complete": True}
        runner._write_completion_checkpoint(self.run_dir, job, prompt, writer, metrics)
        status = {"schema_version": 1, "run_id": "test-run", "status": "failed",
                  "failed_stage": {"agent": "A-Writer", "round": 1},
                  "paper_sha256": self.paper_hash, "research_brief": "synthetic",
                  "base_cost_cap_usd": 6.0, "effective_cost_cap_usd": 6.0,
                  "resume_extra_cost_usd": 0.0, "metrics": {**metrics, "input_tokens": 0,
                  "output_tokens": 0, "total_tokens": 0, "tool_calls": 0},
                  "history": [{"agent": "A-Writer", "state": "building"},
                              {"agent": "A-Writer", "state": "failed"}]}
        runner.write_json(self.run_dir / "run.json", status)
        return config, status, writer

    def test_resume_retries_failed_writer_build_without_calling_writer(self):
        config, _, expected_writer = self._make_writer_build_failure()
        build = {"summary": "Synthetic resumed build", "reports": []}
        with (
            patch.object(runner, "ROOT", self.root),
            patch.object(runner, "_runtime_args", return_value=([], {})),
            patch.object(runner, "_preflight_roles", return_value={}),
            patch.object(runner, "invoke_agent") as invoke,
            patch.object(runner, "live_build", return_value=build) as build_call,
            patch.object(runner, "commit_and_archive", return_value="V8"),
            patch.object(runner, "_publish_outputs"),
            patch.object(runner, "_run_correcter_feedback", return_value={"status": "unavailable"}),
        ):
            result = runner.resume_workflow(config, "test-run", 0.0)
        self.assertEqual(result, 0)
        invoke.assert_not_called()
        build_call.assert_called_once()
        saved = runner.load_json(self.run_dir / runner.OUTPUT_FILES["A-Writer"])
        self.assertEqual(saved["summary"], expected_writer["summary"])
        status = runner.load_json(self.outputs / "run-status.json")
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["version"], "V8")

    def test_writer_build_recovery_reconstructs_handoff_only_from_matching_completion_hash(self):
        config, status, writer = self._make_writer_build_failure()
        handoff = self.run_dir / runner.OUTPUT_FILES["A-Writer"]
        handoff.unlink()
        response = {key: value for key, value in writer.items()
                    if key not in {"schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes"}}
        event = {"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "text", "text": json.dumps(response, ensure_ascii=False)}]}}
        (self.run_dir / "logs/A-Writer-r1.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
        with patch.object(runner, "ROOT", self.root):
            _, _, recovered = runner._load_writer_build_recovery(config, self.run_dir, status)
        self.assertEqual(recovered["changed_files"], writer["changed_files"])
        self.assertEqual(runner.load_json(handoff), recovered)

    def test_writer_build_recovery_rejects_checkpoint_or_input_tampering(self):
        config, status, _ = self._make_writer_build_failure()
        prompt_path = self.run_dir / "jobs/A-Writer-r1.md"
        prompt_path.write_text(prompt_path.read_text() + "tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(runner.WorkflowError, "job or prompt"):
            runner._load_writer_build_recovery(config, self.run_dir, status)
        job = runner.load_json(self.run_dir / "jobs/A-Writer-r1.json")
        prompt_path.write_text(runner._prompt(config, "A-Writer", job, self.run_dir), encoding="utf-8")
        skill = self.run_dir / "skills/skills-paper_writing.md"
        skill.write_text(skill.read_text() + "tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(runner.WorkflowError, "non-Paper Writer input changed"):
            runner._load_writer_build_recovery(config, self.run_dir, status)

    def test_partial_scout_gets_one_retrieval_retry_then_pipeline_continues(self):
        calls = []
        def agent(role, round_number, job, prompt, metrics):
            calls.append((role, round_number))
            if role == "A-Scout":
                if round_number == 1:
                    partial = self._scout(self.run_dir, round_number=1, status="partial", count=3, download=False)
                    partial["papers"][-1]["url"] = ""
                    return partial
                return self._scout(self.run_dir, round_number=2, status="ok", count=5, download=True)
            if role == "A-Researcher":
                return self._researcher(1, self.run_dir)
            main = self.run_dir / "Paper/Work-In-Progress/main.tex"
            main.write_text(main.read_text().replace("Baseline result.", r"\writerrevision{Integrated result.}"))
            return {**{key: job[key] for key in ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")},
                    "status": "ok", "summary": "Integrated accepted idea.", "integrated_idea_ids": ["I1"],
                    "changed_files": ["Work-In-Progress/main.tex"], "unresolved": []}

        def build(run_dir):
            pdf = run_dir / "Paper/Work-In-Progress/main.pdf"
            pdf.write_bytes(b"%PDF-test")
            return {"normal_pdf_sha256": runner.sha256_file(pdf)}

        events = []
        result = runner.execute_pipeline(self.config, "test-run", self.run_dir, self.outputs,
                                         self.paper_hash, agent, build,
                                         lambda state, role, info: events.append((state, role)))
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(calls[:3], [("A-Scout", 1), ("A-Scout", 2), ("A-Researcher", 1)])
        self.assertIn(("revision", "A-Scout"), events)
        self.assertEqual(len(result["scout"]["papers"]), 5)

    def test_scout_controller_reuses_verified_pdf_path_from_previous_overview(self):
        previous = self._scout(self.run_dir)
        runner.validate_agent_payload("A-Scout", previous, self.run_dir, self.config)
        runner.write_json(self.run_dir / runner.OUTPUT_FILES["A-Scout"], previous)
        current = copy.deepcopy(previous)
        old_path = current["papers"][0]["download_path"]
        current["papers"][0]["download_path"] = None
        runner.validate_agent_payload("A-Scout", current, self.run_dir, self.config)
        self.assertEqual(current["papers"][0]["download_path"], old_path)
        self.assertIn(old_path, current["reused_previous_pdf_paths"])

    def test_scout_controller_recovers_a_verified_doi_download_path_from_tool_filename(self):
        scout = self._scout(self.run_dir)
        paper = scout["papers"][0]
        prior_path = paper["download_path"]
        stable = f"Agent-Outputs/A-Scout/papers/{scout_retrieval.doi_pdf_filename(paper['doi'])}"
        (self.run_dir / stable).write_bytes(b"%PDF-1.4 deterministic DOI fixture")
        paper["download_path"] = None
        with patch.object(scout_retrieval, "verify_pdf_text", return_value={"ok": True,
                                                                               "first_page_text": paper["title"]}):
            runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        self.assertEqual(paper["download_path"], stable)
        self.assertEqual(scout["recovered_doi_download_paths"], [stable])
        self.assertFalse((self.run_dir / prior_path).exists())

    def test_scout_drops_missing_path_for_a_known_indexed_source(self):
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json",
                          {"schema_version": 1, "papers": [{"id": "S1", "doi": "10.0000/synthetic1",
                                                              "url": "https://example.org/S1", "title": "Synthetic source 1"}]})
        scout = self._scout(self.run_dir)
        scout["papers"][0]["download_path"] = "Agent-Outputs/A-Scout/papers/stale-old-name.pdf"
        runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        self.assertIsNone(scout["papers"][0]["download_path"])
        self.assertEqual(scout["discarded_missing_download_paths"],
                         ["Agent-Outputs/A-Scout/papers/stale-old-name.pdf"])

    def test_scout_completion_requires_five_verified_or_indexed_papers(self):
        scout = self._scout(self.run_dir)
        self.assertTrue(runner._scout_is_complete(self.run_dir, scout, self.config))
        scout["papers"][0]["download_path"] = None
        self.assertFalse(runner._scout_is_complete(self.run_dir, scout, self.config))
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json",
                          {"schema_version": 1, "papers": [{"id": scout["papers"][0]["id"]}]})
        self.assertTrue(runner._scout_is_complete(self.run_dir, scout, self.config))
        scout["papers"].pop()
        self.assertFalse(runner._scout_is_complete(self.run_dir, scout, self.config))

    def test_persistently_partial_scout_stops_before_researcher(self):
        calls = []
        def agent(role, round_number, job, prompt, metrics):
            calls.append((role, round_number))
            if role == "A-Scout":
                partial = self._scout(self.run_dir, round_number=round_number,
                                      status="partial", count=3, download=False)
                partial["papers"][-1]["url"] = ""
                return partial
            self.fail("Researcher must not receive an incomplete Scout package")
        result = runner.execute_pipeline(self.config, "test-run", self.run_dir, self.outputs,
                                         self.paper_hash, agent,
                                         lambda _run_dir: self.fail("Build must not run"),
                                         lambda *_args: None)
        self.assertEqual(result["outcome"], "scout_incomplete")
        self.assertEqual(calls, [("A-Scout", 1), ("A-Scout", 2)])
        self.assertIn("3/5", result["reason"])

    def test_empty_researcher_handoff_still_invokes_writer_and_builds(self):
        calls = []
        def agent(role, round_number, job, prompt, metrics):
            calls.append(role)
            if role == "A-Scout":
                return self._scout(self.run_dir)
            if role == "A-Researcher":
                payload = self._researcher(1, self.run_dir)
                payload["ideas"] = []
                payload["papers_read"] = []
                payload["prior_papers_reused"] = []
                payload["no_idea_reason"] = "No theorem extension; Writer should make a conservative exposition improvement."
                return payload
            path = self.run_dir / "Paper/Work-In-Progress/main.tex"
            path.write_text(path.read_text().replace("Baseline result.", r"\\writerrevision{Clarified result.}"))
            return {**{key: job[key] for key in ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")},
                    "status": "ok", "summary": "Made a conservative exposition improvement.",
                    "integrated_idea_ids": [], "changed_files": ["Work-In-Progress/main.tex"], "unresolved": []}

        def build(run_dir):
            pdf = run_dir / "Paper/Work-In-Progress/main.pdf"
            pdf.write_bytes(b"%PDF-empty-handoff fixture")
            return {"normal_pdf_sha256": runner.sha256_file(pdf), "highlight_disabled_pdf_sha256": "fixture"}

        result = runner.execute_pipeline(self.config, "test-run", self.run_dir, self.outputs,
                                         self.paper_hash, agent, build, lambda *_args: None)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(calls, ["A-Scout", "A-Researcher", "A-Writer"])
        self.assertEqual(result["writer"]["integrated_idea_ids"], [])

    def test_successful_linear_run_writes_then_builds(self):
        calls = []
        def agent(role, round_number, job, prompt, metrics):
            calls.append((role, round_number))
            if role == "A-Scout":
                return self._scout(self.run_dir)
            if role == "A-Researcher":
                return self._researcher(1, self.run_dir)
            main = self.run_dir / "Paper/Work-In-Progress/main.tex"
            text = main.read_text().replace("Baseline result.",
                                            r"\writerrevision{Synthetic corrected result.}")
            main.write_text(text)
            return {**{key: job[key] for key in ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")},
                    "status": "ok", "summary": "Integrated all Researcher ideas.",
                    "integrated_idea_ids": ["I1"],
                    "changed_files": ["Work-In-Progress/main.tex"], "unresolved": []}

        def build(run_dir):
            writer_handoff = runner.load_json(run_dir / runner.OUTPUT_FILES["A-Writer"])
            self.assertEqual(writer_handoff["summary"], "Integrated all Researcher ideas.")
            self.assertNotIn("build", writer_handoff)
            pdf = run_dir / "Paper/Work-In-Progress/main.pdf"
            pdf.write_bytes(b"%PDF-1.4 compiled synthetic fixture")
            return {"summary": "Synthetic build fixture", "normal_pdf_sha256": runner.sha256_file(pdf),
                    "highlight_disabled_pdf_sha256": "synthetic-hash", "normal_pdf": str(pdf)}

        events = []
        result = runner.execute_pipeline(self.config, "test-run", self.run_dir, self.outputs,
                                         self.paper_hash, agent, build,
                                         lambda state, role, info: events.append((state, role, info)))
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(calls, [("A-Scout", 1), ("A-Researcher", 1), ("A-Writer", 1)])
        self.assertTrue((self.outputs / "A-Researcher.json").is_file())
        self.assertEqual(runner.load_json(self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json")["papers"][0]["id"], "S1")
        self.assertFalse(any(role in {"A-Researcher-Plan", "A-Candidate-Scout", "A-Novelty-Screen", "A-Evaluator"}
                             for _, role, _ in events))
        self.assertEqual(result["writer"]["integrated_idea_ids"], [idea["id"] for idea in result["researcher"]["ideas"]])
        self.assertEqual(result["changed_files"], ["Work-In-Progress/main.tex"])
        for role in ("A-Researcher", "A-Writer"):
            checkpoint = runner.load_json(self.run_dir / "checkpoints" / f"before-{role}-r1.json")
            self.assertEqual(checkpoint["next_stage"], role)
            self.assertEqual(checkpoint["paper_sha256"], self.paper_hash)
            self.assertEqual(checkpoint["job"]["paper_sha256"], self.paper_hash)
            expected_paper_input = ("Paper" if role == "A-Writer"
                                    else "Paper/Work-In-Progress/main.tex")
            self.assertIn(expected_paper_input, checkpoint["job"]["input_hashes"])

    def test_checkpoint_validates_researcher_and_writer_boundaries_and_rejects_tampering(self):
        overview = {"schema_version": 1, "status": "ok", "papers": []}
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Overview.json", overview)
        status = {"run_id": "test-run", "paper_sha256": self.paper_hash}
        for role, round_number in (("A-Researcher", 1), ("A-Writer", 1)):
            job = runner._agent_job(self.config, "test-run", self.run_dir, role, round_number,
                                    self.paper_hash, research_brief="synthetic resume")
            prompt = f"synthetic {role} prompt"
            runner.write_json(self.run_dir / "jobs" / f"{role}-r{round_number}.json", job, compact=True)
            (self.run_dir / "jobs" / f"{role}-r{round_number}.md").write_text(prompt)
            runner._write_stage_checkpoint(self.run_dir, job, prompt, {"provider_cost_usd": 1.0})
            checkpoint = runner.load_json(runner._checkpoint_path(self.run_dir, role, round_number))
            restored_job, restored_prompt = runner._validate_stage_checkpoint(self.run_dir, checkpoint, status)
            self.assertEqual(restored_job, job)
            self.assertEqual(restored_prompt, prompt)
        researcher_path = self.run_dir / runner.OUTPUT_FILES["A-Researcher"]
        researcher_path.write_text('{"tampered":true}')
        writer_checkpoint = runner.load_json(runner._checkpoint_path(self.run_dir, "A-Writer", 1))
        with self.assertRaisesRegex(runner.WorkflowError, "input hashes"):
            runner._validate_stage_checkpoint(self.run_dir, writer_checkpoint, status)

    def test_resume_budget_extension_is_finite_explicit_and_bounded(self):
        with self.assertRaisesRegex(runner.WorkflowError, r"<= \$10.00"):
            runner.resume_workflow(self.config, "missing-run", 10.01)
        with self.assertRaisesRegex(runner.WorkflowError, "finite"):
            runner.resume_workflow(self.config, "missing-run", float("nan"))

    def test_writer_prompt_specifies_two_generation_revision_color_rotation(self):
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Writer", 1, self.paper_hash)
        prompt = runner._prompt(self.config, "A-Writer", job, self.run_dir)
        self.assertIn("Two-generation revision colors", prompt)
        self.assertIn(r"\writerpreviousrevision{...}", prompt)
        self.assertIn(r"\writerrevision{...}", prompt)
        self.assertIn("rotate the incoming revision markup", prompt)
        self.assertIn("preserving the `\\writerrevision` macro declaration", prompt)
        self.assertIn("color 1 (blue)", prompt)
        self.assertIn("color 2 (magenta)", prompt)
        self.assertIn(r"\definecolor{BLUE}{rgb}{0,0,1}", prompt)
        self.assertIn(r"\providecommand{\writerpreviousrevision}[1]{{\color{BLUE}#1}}", prompt)
        self.assertIn(r"\providecommand{\writerrevision}[1]{{\color{magenta}#1}}", prompt)
        self.assertIn(r"\providecommand{\writerpreviousrevision}[1]{{\color{BLUE}#1}}", prompt)
        self.assertIn(r"\definecolor{MAGENTA}{rgb}{1,0,1}", prompt)
        self.assertIn(r"\definecolor{BLUE}{rgb}{0,0,1}", prompt)

    def test_writer_runs_directly_after_researcher_without_a_novelty_gate(self):
        calls = []
        def agent(role, round_number, job, prompt, metrics):
            calls.append((role, round_number))
            if role == "A-Scout":
                return self._scout(self.run_dir)
            if role == "A-Researcher":
                payload = self._researcher(1, self.run_dir)
                payload["summary"] = "Synthetic incremental/correction handoff without novelty approval."
                return payload
            path = self.run_dir / "Paper/Work-In-Progress/main.tex"
            path.write_text(path.read_text().replace("Baseline result.", r"\writerrevision{Integrated result.}"))
            return {**{key: job[key] for key in ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")},
                    "status": "ok", "summary": "Integrated every Researcher idea.",
                    "integrated_idea_ids": [idea["id"] for idea in runner.load_json(self.run_dir / runner.OUTPUT_FILES["A-Researcher"])["ideas"]],
                    "changed_files": ["Work-In-Progress/main.tex"], "unresolved": []}

        def build(run_dir):
            pdf = run_dir / "Paper/Work-In-Progress/main.pdf"
            pdf.write_bytes(b"%PDF-test")
            return {"normal_pdf_sha256": runner.sha256_file(pdf), "highlight_disabled_pdf_sha256": "synthetic-disabled"}

        result = runner.execute_pipeline(self.config, "test-run", self.run_dir, self.outputs,
                                         self.paper_hash, agent, build, lambda *_args: None)
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(calls, [("A-Scout", 1), ("A-Researcher", 1), ("A-Writer", 1)])
        self.assertEqual(result["writer"]["integrated_idea_ids"], ["I1"])
    def test_partial_scout_can_drop_a_verified_stale_cached_pdf(self):
        previous = self._scout(self.run_dir, count=1, download=True)
        runner.validate_agent_payload("A-Scout", previous, self.run_dir, self.config)
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Overview.json", previous)
        current = copy.deepcopy(previous)
        current["status"] = "partial"
        current["papers"][0]["download_path"] = None
        runner.validate_agent_payload("A-Scout", current, self.run_dir, self.config)
        self.assertFalse((self.run_dir / previous["papers"][0]["download_path"]).exists())

    def test_scout_assigns_a_fresh_id_when_source_identity_changes(self):
        registry = {"schema_version": 1, "papers": [{"id": "S5", "doi": "",
                    "url": "https://old.example.org/source", "title": "Old paper"}]}
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json", registry)
        scout = self._scout(self.run_dir, count=6)
        runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        self.assertEqual(scout["papers"][-1]["id"], "S6")
        self.assertEqual(scout["id_normalizations"][0]["reported_id"], "S5")
        self.assertEqual(scout["id_normalizations"][0]["assigned_id"], "S6")

    def test_create_run_mounts_previous_correcter_feedback_for_researcher(self):
        project = self.root / "feedback-project"
        shutil.copytree(self.run_dir / "Paper", project / "Paper")
        shutil.copytree(self.run_dir / "skills", project / "skills")
        shutil.copytree(Path(__file__).resolve().parents[2] / "agents", project / "agents")
        (project / "paper_workflow").mkdir(parents=True)
        shutil.copy2(Path(__file__).resolve().parents[2] / "paper_workflow/scout_retrieval.py",
                     project / "paper_workflow/scout_retrieval.py")
        outputs = project / "Agent-Outputs"
        previous = {"schema_version": 1, "status": "ok", "run_id": "previous-writer",
                    "writer_version": "V7", "feedback": [{"id": "F1", "potential_direction": "Test a controlled quotient."}]}
        runner.write_json(outputs / "A-Correcter/Feedback.json", previous)
        config = copy.deepcopy(self.config)
        with patch.object(runner, "ROOT", project):
            next_run, paper_hash = runner.create_run(config, "next-feedback-run", outputs)
            mounted = runner.load_json(next_run / runner.CORRECTER_PRIOR_FEEDBACK)
            policy = runner.role_policy("A-Researcher", next_run)
            job = runner._agent_job(config, "next-feedback-run", next_run, "A-Researcher", 1, paper_hash)
            prompt = runner._prompt(config, "A-Researcher", job, next_run)
        self.assertEqual(mounted, previous)
        self.assertIn(runner.CORRECTER_PRIOR_FEEDBACK, policy["read_only"])
        self.assertIn("A-Correcter feedback from the prior Writer run", prompt)
        self.assertIn("Test a controlled quotient", mounted["feedback"][0]["potential_direction"])

    def test_researcher_scope_can_search_for_prior_feedback_techniques(self):
        (self.run_dir / "scout_retrieval.py").write_text("# retrieval tool fixture\n")
        runner.write_json(self.run_dir / runner.CORRECTER_PRIOR_FEEDBACK,
                          {"schema_version": 1, "status": "ok", "feedback": [{"id": "F1"}]})
        scout = self._scout(self.run_dir)
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Overview.json", scout)
        registry = {"schema_version": 1, "papers": [
            {"id": f"S{i}", "doi": f"10.0000/synthetic{i}", "url": f"https://example.org/S{i}"}
            for i in range(1, 5)]}
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json", registry)
        researcher_policy = runner.role_policy("A-Researcher", self.run_dir)
        self.assertNotIn("Agent-Outputs/A-Scout/papers/S5.pdf", researcher_policy["read_only"])
        self.assertNotIn("Agent-Outputs/A-Scout/papers/S1.pdf", researcher_policy["read_only"])
        self.assertNotIn("Agent-Outputs/A-Scout/papers", researcher_policy["read_only"])
        self.assertEqual(researcher_policy["network"], "approved-public-search-and-source-read")
        self.assertIn("scout_retrieval.py", researcher_policy["read_only"])
        self.assertIn(runner.CORRECTER_PRIOR_FEEDBACK, researcher_policy["read_only"])
        self.assertIn("bash", researcher_policy["tools"])
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Researcher", 1, self.paper_hash)
        prompt = runner._prompt(self.config, "A-Researcher", job, self.run_dir)
        self.assertIn("A-Correcter feedback from the prior Writer run", prompt)
        self.assertIn("search-topic", prompt)

    def test_researcher_canonicalizes_indexed_sources_as_prior_reuse(self):
        scout = self._scout(self.run_dir)
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Overview.json", scout)
        registry = {"schema_version": 1, "papers": [
            {"id": f"S{i}", "doi": f"10.0000/synthetic{i}", "url": f"https://example.org/S{i}",
             "title": f"Synthetic source {i}", "summary": f"Previously verified synthetic summary {i}.",
             "locator": "Theorem 1"} for i in range(1, 6)]}
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json", registry)
        researcher = self._researcher(1, self.run_dir)
        researcher["status"] = "partial"
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Researcher", 1, self.paper_hash)
        runner.validate_envelope(researcher, job)
        runner.validate_agent_payload("A-Researcher", researcher, self.run_dir, self.config)
        self.assertEqual(researcher["status"], "ok")
        self.assertEqual(researcher["papers_read"], [])
        self.assertEqual(researcher["prior_papers_reused"], ["S1", "S2", "S3", "S4", "S5"])
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Researcher", 1, self.paper_hash)
        prompt = runner._prompt(self.config, "A-Researcher", job, self.run_dir)
        self.assertIn("Return papers_read as [] exactly", prompt)
        researcher_prompt = (Path(__file__).resolve().parents[2] / "agents/prompts/A-Researcher.md").read_text()
        self.assertIn("A-Scout owns primary source retrieval and full-text verification", researcher_prompt)

    def test_researcher_pdf_read_claim_requires_successful_read_tool_calls(self):
        scout = self._scout(self.run_dir)
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Overview.json", scout)
        researcher = self._researcher(1, self.run_dir)
        with self.assertRaisesRegex(runner.WorkflowError, "without successful PDF text extraction/read calls"):
            runner.validate_researcher_pdf_reads(researcher, self.run_dir, set())
        observed = {paper["download_path"] for paper in scout["papers"]}
        runner.validate_researcher_pdf_reads(researcher, self.run_dir, observed)
        path = scout["papers"][0]["download_path"]
        command = f"gs -q -sDEVICE=txtwrite -o - -dFirstPage=1 -dLastPage=3 {path} | head -160"
        self.assertEqual(runner._ghostscript_source_paths(command, [path]), [path])
        self.assertTrue(runner._valid_pdf_text_output("extracted source text " * 10))
        self.assertEqual(runner._ghostscript_source_paths(f"cat {path}", [path]), [])
        self.assertFalse(runner._valid_pdf_text_output("error: command not found"))

    def test_researcher_must_read_new_sources_and_reuse_only_indexed_ids(self):
        scout = self._scout(self.run_dir)
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Overview.json", scout)
        researcher = self._researcher(1, self.run_dir)
        researcher["ideas"][0]["kind"] = "correctness repair"
        researcher["ideas"][0]["source_context"] = {"current_claim": "Synthetic baseline claim.",
                                                       "assumptions": "A1", "locator": "Results, Eq. 1"}
        researcher["ideas"][0]["prior_work"] = [{"source": "S1", "difference": "Synthetic source comparison"}]
        researcher["ideas"][0]["assumptions"] = "Synthetic assumption"
        researcher["ideas"][0]["caveats"] = "Synthetic caveat"
        researcher["ideas"][0]["paper_changes"] = [{"file": "Paper/Work-In-Progress/main.tex",
                                                     "locator": "Results, Eq. 1", "action": "Add the result."}]
        researcher["ideas"][0]["falsification_test"] = {"boundary case": "Check the equality at zero.",
                                                         "numeric case": "Compare both sides for a qubit."}
        researcher["narrative_plan"] = "Synthetic one-paragraph narrative plan."
        runner.validate_agent_payload("A-Researcher", researcher, self.run_dir, self.config)
        self.assertEqual(researcher["ideas"][0]["kind"], "correction")
        self.assertIsInstance(researcher["ideas"][0]["source_context"], str)
        self.assertEqual(researcher["ideas"][0]["prior_work"], ["S1: Synthetic source comparison"])
        self.assertEqual(researcher["narrative_plan"], ["Synthetic one-paragraph narrative plan."])
        self.assertEqual(researcher["ideas"][0]["assumptions"], ["Synthetic assumption"])
        self.assertIn("Paper/Work-In-Progress/main.tex — Results, Eq. 1:\nAdd the result.",
                      researcher["ideas"][0]["paper_changes"])
        self.assertEqual(researcher["ideas"][0]["falsification_test"],
                         "boundary case: Check the equality at zero.\nnumeric case: Compare both sides for a qubit.")
        researcher_prompt = (Path(__file__).resolve().parents[2] / "agents/prompts/A-Researcher.md").read_text()
        self.assertIn("implementation-ready `paper_changes`", researcher_prompt)
        self.assertIn("small `read` windows", researcher_prompt)
        self.assertIn("novelty is not an acceptance condition", researcher_prompt)
        self.assertIn("Forward every supported improvement", researcher_prompt)
        bad = copy.deepcopy(researcher)
        bad["papers_read"] = []
        bad["prior_papers_reused"] = [f"S{i}" for i in range(1, 6)]
        with self.assertRaisesRegex(runner.WorkflowError, "already in Read-Papers.json"):
            runner.validate_agent_payload("A-Researcher", bad, self.run_dir, self.config)

    def test_researcher_accepts_more_than_three_corrections_without_novelty_fields(self):
        scout = self._scout(self.run_dir)
        runner.write_json(self.run_dir / runner.OUTPUT_FILES["A-Scout"], scout)
        researcher = self._researcher(1, self.run_dir)
        first = researcher["ideas"][0]
        first.pop("novelty_delta", None)
        first.pop("falsification_test", None)
        first.pop("proof", None)
        for number in range(2, 5):
            idea = copy.deepcopy(first)
            idea["id"] = f"I{number}"
            idea["title"] = f"Supported correction {number}"
            researcher["ideas"].append(idea)
        runner.validate_agent_payload("A-Researcher", researcher, self.run_dir, self.config)
        self.assertEqual(len(researcher["ideas"]), 4)
        self.assertTrue(all("novelty_delta" not in idea for idea in researcher["ideas"]))

    def test_full_run_config_places_correcter_after_writer(self):
        self.assertEqual(tuple(self.config["roles"]), ("A-Scout", "A-Researcher", "A-Writer", "A-Correcter"))
        self.assertEqual(tuple(self.config["roles"]), runner.AGENT_ORDER)
        self.assertNotIn("A-Evaluator", self.config["roles"])
        self.assertEqual(tuple(self.config["standalone_roles"]), ())

    def test_role_permissions_are_narrow_and_writer_allowlist_is_exact(self):
        self.assertEqual(tuple(self.config["roles"]), ("A-Scout", "A-Researcher", "A-Writer", "A-Correcter"))
        scout = runner.role_policy("A-Scout")
        researcher = runner.role_policy("A-Researcher")
        writer = runner.role_policy("A-Writer")
        baseline = self.run_dir / "source-writer-files"
        baseline.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "scout_retrieval.py").write_text("# scout search tool fixture\n")
        correcter = runner.role_policy("A-Correcter", self.run_dir)
        self.assertEqual(scout["write"], ["Agent-Outputs/A-Scout/papers"])
        self.assertIn("scout_retrieval.py", scout["read_only"])
        self.assertIn("bash", scout["tools"])
        self.assertEqual(nono_launcher.PI_TOOL_MAPPING["bash"], "bash")
        self.assertNotIn("Paper", scout["write"])
        self.assertEqual(researcher["write"], [])
        self.assertIn("Agent-Outputs/A-Scout/Overview.json", researcher["read_only"])
        self.assertIn("Agent-Outputs/A-Scout/Read-Papers.json", researcher["read_only"])
        self.assertNotIn("Agent-Outputs/A-Researcher-Candidates.json", researcher["read_only"])
        self.assertNotIn("Agent-Outputs/A-Novelty-Screen.json", researcher["read_only"])
        self.assertEqual(correcter["write"], [])
        self.assertIn("Paper", correcter["read_only"])
        self.assertIn("Agent-Outputs/A-Writer.json", correcter["read_only"])
        self.assertIn("source-writer-files", correcter["read_only"])
        self.assertIn("scout_retrieval.py", correcter["read_only"])
        self.assertEqual(correcter["network"], "approved-public-search-and-source-read")
        self.assertNotIn("write", correcter["tools"])
        self.assertEqual(set(writer["write"]), {"Paper/" + path for path in runner.WRITER_FILES})
        self.assertIn("Paper", writer["read_only"])
        self.assertIn("Agent-Outputs/A-Researcher.json", writer["read_only"])
        self.assertNotIn("AI-Versions", writer["write"])
        self.assertEqual(runner.next_version(self.root / "AI-Versions"), "V1")
        self.assertEqual(self.config["roles"]["A-Researcher"]["max_output_tokens"], 30000)
        self.assertEqual(self.config["limits"]["max_total_output_tokens"], 500000)
        self.assertEqual(self.config["limits"]["max_stream_bytes"], 32 * 1024 * 1024)

    def test_timeout_kills_process_and_output_is_bounded(self):
        with self.assertRaisesRegex(runner.WorkflowError, "timed out"):
            runner._run_bounded([sys.executable, "-c", "import time; time.sleep(10)"],
                                cwd=self.root, timeout=1, byte_limit=1000,
                                stdout_path=self.root / "timeout.out", stderr_path=self.root / "timeout.err",
                                label="synthetic timeout")
        with self.assertRaisesRegex(runner.WorkflowError, "stream limit"):
            runner._run_bounded([sys.executable, "-c", "print('x'*1000)"],
                                cwd=self.root, timeout=3, byte_limit=10,
                                stdout_path=self.root / "large.out", stderr_path=self.root / "large.err",
                                label="synthetic output limit")
        start = "import json,time; print(json.dumps({'type':'tool_execution_start','toolCallId':'t1','toolName':'bash'}),flush=True); time.sleep(5)"
        with self.assertRaisesRegex(runner.WorkflowError, "tool bash exceeded 1s"):
            runner._run_bounded([sys.executable, "-c", start], cwd=self.root, timeout=5,
                                byte_limit=1000, stdout_path=self.root / "tool-timeout.out",
                                stderr_path=self.root / "tool-timeout.err", per_tool_timeout_sec=1,
                                label="synthetic per-tool timeout")
        pid_file = self.root / "detached.pid"
        child = ("import subprocess,sys,time; "
                 "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
                 "start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                 f"open({str(pid_file)!r},'w').write(str(p.pid)); time.sleep(30)")
        with self.assertRaisesRegex(runner.WorkflowError, "timed out"):
            runner._run_bounded([sys.executable, "-c", child], cwd=self.root, timeout=1,
                                byte_limit=1000, stdout_path=self.root / "detached.out",
                                stderr_path=self.root / "detached.err", label="detached-child timeout")
        child_pid = int(pid_file.read_text())
        status = subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        self.assertFalse(status and not status.startswith("Z"), "detached child survived workflow timeout")

    def test_prompt_assigns_provenance_stamping_to_controller_and_keeps_shell_instruction(self):
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Scout", 1, self.paper_hash)
        prompt = runner._prompt(self.config, "A-Scout", job, self.run_dir)
        shape = prompt.split("Required response shape", 1)[1].split("Handoff contract", 1)[0]
        self.assertNotIn('"schema_version":1', shape)
        self.assertIn("trusted controller stamps", shape)
        self.assertIn("deterministic retrieval tool", prompt)
        self.assertIn("Find **five** useful, verified research sources", prompt)
        self.assertIn("finite search plan", prompt)
        self.assertIn("Metadata preflight", prompt)
        self.assertIn("repair it from the source, replace the record, or omit it", prompt)
        self.assertIn("Use the key `outcome` (not `result`)", prompt)
        self.assertIn("12,000 UTF-8 bytes", prompt)
        self.assertNotIn("User comments for this run", prompt)

    def test_scout_accepts_empty_queries_when_sources_are_already_indexed(self):
        scout = self._scout(self.run_dir)
        scout["queries"] = []
        runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        self.assertEqual(scout["queries"], [])

    def test_scout_rejects_missing_author_metadata(self):
        scout = self._scout(self.run_dir)
        scout["papers"][0]["authors"] = ""
        with self.assertRaisesRegex(runner.WorkflowError, "paper.authors must be nonempty"):
            runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)

    def test_scout_fills_missing_legacy_read_timestamp_with_current_date(self):
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json",
                          {"schema_version": 1, "papers": [{"id": "S1"}]})
        scout = self._scout(self.run_dir)
        scout["papers"][0].pop("retrieved_at")
        runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        self.assertRegex(scout["papers"][0]["retrieved_at"], r"^20\d{2}-\d{2}-\d{2}$")

    def test_scout_reuses_persistent_read_timestamp_when_retrieved_at_is_missing(self):
        registry = {"schema_version": 1, "papers": [{"id": "S1", "read_at": "2026-01-02T03:04:05Z"}]}
        runner.write_json(self.run_dir / "Agent-Outputs/A-Scout/Read-Papers.json", registry)
        scout = self._scout(self.run_dir, status="partial", count=1, download=False)
        scout["papers"][0].pop("retrieved_at")
        runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        self.assertEqual(scout["papers"][0]["retrieved_at"], registry["papers"][0]["read_at"])

    def test_scout_query_result_alias_is_canonicalized(self):
        scout = self._scout(self.run_dir, status="partial", count=1, download=False)
        scout["queries"] = [{"query": "synthetic topic", "result": "Search completed."}]
        runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        self.assertEqual(scout["queries"][0], {"query": "synthetic topic", "outcome": "Search completed."})

    def test_scout_query_outcome_enforces_utf8_byte_limit(self):
        for outcome in ("x" * 12000, "é" * 6000):
            with self.subTest(bytes=len(outcome.encode("utf-8"))):
                scout = self._scout(self.run_dir, status="partial", count=1, download=False)
                scout["queries"][0]["outcome"] = outcome
                runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        scout = self._scout(self.run_dir, status="partial", count=1, download=False)
        scout["queries"][0]["outcome"] = "é" * 6001
        with self.assertRaisesRegex(runner.WorkflowError, "outcome must be nonempty and <= 12000 UTF-8 bytes"):
            runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)

    def test_scout_query_outcome_rejects_empty_and_missing_fields_clearly(self):
        scout = self._scout(self.run_dir, status="partial", count=1, download=False)
        scout["queries"][0]["outcome"] = "  "
        with self.assertRaisesRegex(runner.WorkflowError, "queries\\[1\\]\\.outcome must be nonempty"):
            runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)
        scout = self._scout(self.run_dir, status="partial", count=1, download=False)
        scout["queries"][0].pop("outcome")
        with self.assertRaisesRegex(runner.WorkflowError, "queries\\[1\\]\\.outcome is missing"):
            runner.validate_agent_payload("A-Scout", scout, self.run_dir, self.config)

    def test_research_brief_is_injected_into_researcher_job(self):
        with patch.object(runner, "ROOT", self.run_dir):
            default_brief = runner._default_research_brief(self.config)
        self.assertIn("Baseline.", default_brief)
        brief = "Investigate corrections and incremental results about record-conditioned sample instruments."
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Researcher", 1, self.paper_hash,
                                research_brief=brief)
        prompt = runner._prompt(self.config, "A-Researcher", job, self.run_dir)
        self.assertEqual(job["research_brief"], brief)
        self.assertEqual(job["researcher_comments"], "")
        self.assertIn(brief, prompt)
        self.assertIn("novelty is not an acceptance condition", prompt)

    def test_numeric_run_ids_advance_past_existing_runs_and_are_not_reused(self):
        runs = self.outputs / "runs"
        for name in ("legacy-custom-run", "run-000002", "run-000009"):
            (runs / name).mkdir(parents=True)
        run_id = runner._new_run_id(self.outputs)
        self.assertEqual(run_id, "run-000010")
        (runs / run_id).mkdir()
        self.assertEqual(runner._new_run_id(self.outputs), "run-000011")
        shutil.rmtree(runs)
        self.assertEqual(runner._new_run_id(self.outputs), "run-000012")

    def test_workflow_lock_prevents_concurrent_run_id_allocations(self):
        lock = runner.run_lock(self.outputs)
        try:
            with self.assertRaisesRegex(runner.WorkflowError, "Another paper workflow run is active"):
                runner.run_lock(self.outputs)
        finally:
            lock.close()

    def test_full_run_persists_user_comments_under_sequential_run_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paper = root / "Paper"
            for relative in runner.WRITER_FILES:
                path = paper / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic manuscript\n", encoding="utf-8")
            (root / "skills").mkdir()
            (root / "paper_workflow").mkdir()
            shutil.copy2(Path(runner.__file__).with_name("scout_retrieval.py"),
                         root / "paper_workflow/scout_retrieval.py")
            outputs = root / "Agent-Outputs"
            (outputs / "runs/run-000005").mkdir(parents=True)
            (outputs / "runs/legacy-run").mkdir()
            config_file = root / "agent-workflow.json"
            config_file.write_text("{}", encoding="utf-8")
            config = copy.deepcopy(self.config)
            config["paths"].update({"paper": "Paper", "outputs": "Agent-Outputs",
                                    "main_tex": runner.WRITER_FILES[0]})
            metrics = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                       "provider_cost_usd": 0.0, "tool_calls": 0, "cost_complete": True,
                       "roles": {}}
            with (
                patch.object(runner, "ROOT", root),
                patch.object(runner, "CONFIG_FILE", config_file),
                patch.object(runner, "_runtime_args", return_value=([], {})),
                patch.object(runner, "_preflight_roles", return_value={}),
                patch.object(runner, "execute_pipeline", return_value={
                    "outcome": "scout_incomplete", "reason": "synthetic stop", "metrics": metrics}) as execute,
            ):
                code = runner.run_workflow(config, research_brief="fixed default objective",
                                           researcher_comments="Focus on the proof detail.")
            self.assertEqual(code, 2)
            status = runner.load_json(outputs / "run-status.json")
            self.assertEqual(status["run_id"], "run-000006")
            self.assertEqual(status["researcher_comments"], "Focus on the proof detail.")
            self.assertEqual(execute.call_args.kwargs["researcher_comments"], "Focus on the proof detail.")

    def test_run_comments_are_injected_for_scout_and_researcher_only_and_survive_checkpoint(self):
        comments = "Please focus on the source comparison and clarify the central assumption."
        status = {"run_id": "test-run", "paper_sha256": self.paper_hash,
                  "research_brief": "default research objective", "researcher_comments": comments}
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Researcher", 1,
                                self.paper_hash, research_brief=status["research_brief"],
                                researcher_comments=comments)
        prompt = runner._prompt(self.config, "A-Researcher", job, self.run_dir)
        self.assertEqual(job["researcher_comments"], comments)
        self.assertIn(comments, prompt)
        self.assertIn("guidance, not evidence", prompt)
        runner.write_json(self.run_dir / "jobs/A-Researcher-r1.json", job, compact=True)
        (self.run_dir / "jobs/A-Researcher-r1.md").write_text(prompt, encoding="utf-8")
        runner._write_stage_checkpoint(self.run_dir, job, prompt, {"provider_cost_usd": 0.0})
        checkpoint = runner.load_json(runner._checkpoint_path(self.run_dir, "A-Researcher", 1))
        restored_job, restored_prompt = runner._validate_stage_checkpoint(self.run_dir, checkpoint, status)
        self.assertEqual(restored_job["researcher_comments"], comments)
        self.assertEqual(restored_prompt, prompt)
        tampered_status = {**status, "researcher_comments": "changed after checkpoint"}
        with self.assertRaisesRegex(runner.WorkflowError, "comments do not match"):
            runner._validate_stage_checkpoint(self.run_dir, checkpoint, tampered_status)
        scout_job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Scout", 1,
                                      self.paper_hash, researcher_comments=comments)
        scout_prompt = runner._prompt(self.config, "A-Scout", scout_job, self.run_dir)
        self.assertEqual(scout_job["researcher_comments"], comments)
        self.assertIn(comments, scout_prompt)
        self.assertEqual(scout_prompt.count(comments), 1)
        self.assertIn("specify a research field or topic", scout_prompt)
        self.assertIn("no research topic", scout_prompt)
        self.assertIn("not evidence", scout_prompt)

        nonresearch_comments = "Please keep the source overview concise."
        nonresearch_job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Scout", 1,
                                            self.paper_hash, researcher_comments=nonresearch_comments)
        nonresearch_prompt = runner._prompt(self.config, "A-Scout", nonresearch_job, self.run_dir)
        self.assertIn(nonresearch_comments, nonresearch_prompt)
        self.assertIn("follow the default manuscript-derived search plan unchanged", nonresearch_prompt)

        writer_job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Writer", 1,
                                       self.paper_hash, researcher_comments=comments)
        correcter_job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Correcter", 1,
                                          self.paper_hash, researcher_comments=comments)
        writer_prompt = runner._prompt(self.config, "A-Writer", writer_job, self.run_dir)
        correcter_prompt = runner._prompt(self.config, "A-Correcter", correcter_job, self.run_dir)
        self.assertEqual(writer_job["researcher_comments"], "")
        self.assertEqual(correcter_job["researcher_comments"], "")
        self.assertNotIn(comments, writer_prompt)
        self.assertNotIn(comments, correcter_prompt)

    def test_researcher_comments_text_file_utf8_and_size_are_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "comments.txt"
            path.write_text("  Clarify the proof. \n", encoding="utf-8")
            self.assertEqual(runner._read_researcher_comments(file_path=str(path)), "Clarify the proof.")
            path.write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(runner.WorkflowError, "valid UTF-8"):
                runner._read_researcher_comments(file_path=str(path))
        self.assertEqual(runner._read_researcher_comments("  Focus on corrections.  "), "Focus on corrections.")
        with self.assertRaisesRegex(runner.WorkflowError, "either --researcher-comments"):
            runner._read_researcher_comments("text", "some-file")
        with self.assertRaisesRegex(runner.WorkflowError, "4000 UTF-8 bytes"):
            runner._read_researcher_comments("é" * 2001)

    def test_correcter_feedback_schema_carries_web_technique_references(self):
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Correcter", 1, self.paper_hash)
        feedback = {**{key: job[key] for key in
                       ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")},
                    "status": "ok", "summary": "Two exploratory proof-technique leads.",
                    "feedback": [{"id": "F1", "manuscript_area": "rollout proof",
                                  "potential_direction": "Investigate sharper bounded-depth action-selection bounds.",
                                  "techniques": [{"name": "matrix convexity inequality",
                                                  "source_title": "A technique paper",
                                                  "authors": ["Example Author"], "year": 2024,
                                                  "doi": "10.1234/technique",
                                                  "url": "https://doi.org/10.1234/technique"}]}],
                    "queries": [{"query": "matrix convexity inequality sample information proof", "outcome": "Found a primary source and a theorem-level technique name."}],
                    "limitations": "Exploratory lead; no novelty or correctness conclusion."}
        runner.validate_envelope(feedback, job)
        runner.validate_agent_payload("A-Correcter", feedback, self.run_dir, self.config)
        technique = feedback["feedback"][0]["techniques"][0]
        self.assertEqual(technique["name"], "matrix convexity inequality")
        self.assertEqual(technique["authors"], "Example Author")
        self.assertEqual(technique["year"], "2024")

    def test_correcter_feedback_failure_is_nonblocking(self):
        events = []
        metrics = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                   "provider_cost_usd": 0.0, "tool_calls": 0, "cost_complete": True}
        def fail_agent(*_args):
            raise runner.WorkflowError("public web unavailable")
        result = runner._run_correcter_feedback(
            self.config, "test-run", self.run_dir, self.outputs, self.paper_hash, "V7", metrics,
            fail_agent, lambda state, role, info: events.append((state, role, info)))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn(("feedback_unavailable", "A-Correcter"), [(state, role) for state, role, _ in events])
        saved = runner.load_json(self.outputs / "A-Correcter/Feedback.json")
        self.assertEqual(saved["status"], "unavailable")

    def test_correcter_prompt_reviews_writer_diff_and_does_not_gate(self):
        baseline = self.run_dir / "source-writer-files"
        baseline.mkdir(parents=True, exist_ok=True)
        job = runner._agent_job(self.config, "correct-test", self.run_dir, "A-Correcter", 1, self.paper_hash)
        prompt = runner._prompt(self.config, "A-Correcter", job, self.run_dir)
        self.assertIn("proof-technique feedback", prompt)
        self.assertIn("search-topic", prompt)
        self.assertIn("Do not rate novelty", prompt)
        self.assertIn("or block publication", prompt)

    def test_tool_count_is_retained_when_handoff_validation_fails(self):
        script = self.root / "fake-pi-launcher.py"
        script.write_text("\n".join([
            "import json,sys",
            "job=json.load(open(sys.argv[2]))",
            "env={k:job[k] for k in ('schema_version','run_id','agent','round','paper_sha256','input_hashes')}",
            "env.update(status='ok',summary='bad version',papers=[{'id':'S1'}],techniques=[],queries=[],limitations='x')",
            "env['status']='invalid'",
            "msg={'role':'assistant','stopReason':'stop','content':[{'type':'text','text':json.dumps(env)}],",
            "'usage':{'input':1,'output':1,'totalTokens':2,'cost':{'total':0.001}}}",
            "print(json.dumps({'type':'tool_execution_start','toolCallId':'t1','toolName':'bash'}))",
            "print(json.dumps({'type':'message_end','message':msg}))",
            "print(json.dumps({'type':'agent_settled','aborted':False}))",
        ]) + "\n")
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Scout", 1, self.paper_hash)
        metrics = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                   "provider_cost_usd": 0.0, "tool_calls": 0, "cost_complete": True}
        launcher = [sys.executable, str(script)]
        with self.assertRaisesRegex(runner.WorkflowError, "status"):
            runner.invoke_agent(self.config, self.run_dir, job, "prompt", launcher, metrics, lambda *_: None)
        self.assertEqual(metrics["tool_calls"], 1)
        status = {"schema_version": 1, "run_id": "test-run", "status": "failed",
                  "history": [], "metrics": metrics}
        runner._record_status(self.outputs, self.run_dir, status, "A-Scout", {"error": "invalid envelope"})
        saved = runner.load_json(self.outputs / "run-status.json")
        self.assertEqual(saved["metrics"]["tool_calls"], 1)

    def test_invoke_agent_reports_budget_exceeded_provider_errors_actionably(self):
        runner.write_json(self.run_dir / runner.OUTPUT_FILES["A-Scout"], self._scout(self.run_dir))
        script = self.root / "fake-pi-budget-error.py"
        script.write_text("\n".join([
            "import json,sys",
            "job=json.load(open(sys.argv[2]))",
            "msg={'role':'assistant','stopReason':'error','content':[],",
            "'errorMessage':'HTTP 402: {\"error\":{\"message\":\"Api key Monthly budget Limit Exceeded.\",\"code\":\"BUDGET_EXCEEDED\"}}',",
            "'usage':{'input':0,'output':0,'totalTokens':0,'cost':{'total':0}}}",
            "print(json.dumps({'type':'message_end','message':msg}))",
            "print(json.dumps({'type':'agent_settled','aborted':False}))",
        ]) + "\n")
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Researcher", 1, self.paper_hash)
        metrics = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                   "provider_cost_usd": 0.0, "tool_calls": 0, "cost_complete": True}
        launcher = [sys.executable, str(script)]
        with self.assertRaisesRegex(runner.WorkflowError, "provider budget exceeded"):
            runner.invoke_agent(self.config, self.run_dir, job, "prompt", launcher, metrics, lambda *_: None)

    def test_invoke_agent_includes_generic_provider_error_detail(self):
        script = self.root / "fake-pi-generic-error.py"
        script.write_text("\n".join([
            "import json,sys",
            "job=json.load(open(sys.argv[2]))",
            "msg={'role':'assistant','stopReason':'error','content':[],",
            "'errorMessage':'HTTP 500: backend unavailable',",
            "'usage':{'input':0,'output':0,'totalTokens':0,'cost':{'total':0}}}",
            "print(json.dumps({'type':'message_end','message':msg}))",
            "print(json.dumps({'type':'agent_settled','aborted':False}))",
        ]) + "\n")
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Scout", 1, self.paper_hash)
        metrics = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                   "provider_cost_usd": 0.0, "tool_calls": 0, "cost_complete": True}
        launcher = [sys.executable, str(script)]
        with self.assertRaisesRegex(runner.WorkflowError, "stopped with error: HTTP 500: backend unavailable"):
            runner.invoke_agent(self.config, self.run_dir, job, "prompt", launcher, metrics, lambda *_: None)

    def test_scout_retrieval_helpers_deduplicate_cache_and_classify_provider_errors(self):
        records = [
            {"doi": "10.1000/X", "title": "first"},
            {"doi": "https://doi.org/10.1000/x", "title": "duplicate"},
            {"url": "https://example.org/paper", "title": "second"},
        ]
        kept, discarded = scout_retrieval.deduplicate_records(records, maximum=2)
        self.assertEqual([item["title"] for item in kept], ["first", "second"])
        self.assertEqual([item["title"] for item in discarded], ["duplicate"])
        self.assertEqual(scout_retrieval.classify_http_status(429), "rate_limited")
        self.assertEqual(scout_retrieval.classify_http_status(404), "permanent_not_found")
        self.assertEqual(scout_retrieval.classify_http_status(503), "transient_server_error")
        cache_key = scout_retrieval.provider_cache_key("Crossref", "sample mdp")
        self.assertEqual(len(cache_key), 64)

    def test_topic_search_displays_only_complete_deduplicated_records_deterministically(self):
        crossref = [
            {"DOI": "10.1000/ABC", "title": ["Sample policy planning"],
             "author": [{"given": "Ada", "family": "Lovelace"}],
             "issued": {"date-parts": [[2023, 4, 1]]}, "container-title": ["Journal of Sample Control"],
             "link": [{"content-type": "application/pdf", "URL": "https://papers.example/a.pdf"}]},
            {"DOI": "10.1000/incomplete", "title": ["Incomplete metadata record"],
             "issued": {"date-parts": [[2021]]}, "container-title": ["Journal"], "link": []},
        ]
        openalex = [
            {"doi": "https://doi.org/10.1000/abc", "title": "Sample policy planning",
             "authorships": [{"author": {"display_name": "Ada Lovelace"}}], "publication_year": 2023,
             "primary_location": {"source": {"display_name": "Journal of Sample Control"}},
             "best_oa_location": {"pdf_url": "https://papers.example/a-openalex.pdf"},
             "abstract_inverted_index": {"Sample": [0], "policy": [1], "planning": [2]}},
            {"doi": "https://doi.org/10.1000/second", "title": "Sample decision dynamics",
             "authorships": [{"author": {"display_name": "Grace Hopper"}}], "publication_year": 2022,
             "primary_location": {"source": {"display_name": "Decision Journal"}},
             "best_oa_location": {"pdf_url": "https://papers.example/b.pdf"}},
        ]
        with (patch.object(scout_retrieval, "search_crossref", return_value=crossref),
              patch.object(scout_retrieval, "search_openalex", return_value=openalex),
              patch.object(scout_retrieval, "search_arxiv", return_value='<feed xmlns="http://www.w3.org/2005/Atom"/>')):
            first = scout_retrieval.search_topic("sample policy", self.root / "cache", limit=10)
            second = scout_retrieval.search_topic("sample policy", self.root / "cache", limit=10)
        self.assertEqual(first, second)
        self.assertEqual([item["doi"] for item in first["papers"]], ["10.1000/abc", "10.1000/second"])
        self.assertEqual(first["excluded_incomplete_count"], 1)
        self.assertTrue(all(not scout_retrieval.metadata_missing(item) for item in first["papers"]))
        self.assertEqual(first["papers"][0]["authors"], "Ada Lovelace")
        self.assertEqual(first["papers"][0]["pdf_url"], "https://papers.example/a.pdf")

    def test_topic_search_cli_returns_json_candidates(self):
        expected = {"ok": True, "topic": "sample control", "papers": [{"doi": "10.1/example"}]}
        output = io.StringIO()
        with patch.object(scout_retrieval, "search_topic", return_value=expected) as search, redirect_stdout(output):
            code = scout_retrieval.main(["search-topic", "sample control", "--limit", "7", "--no-cache"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertIsNone(search.call_args.args[1])

    def test_doi_download_returns_verified_metadata_and_stable_file(self):
        crossref = {"message": {"DOI": "10.1234/example", "title": ["A Deterministic Paper"],
            "author": [{"given": "Katherine", "family": "Johnson"}], "issued": {"date-parts": [[2024]]},
            "container-title": ["Journal of Deterministic Tests"], "URL": "https://doi.org/10.1234/example",
            "link": [{"content-type": "application/pdf", "URL": "https://papers.example/paper.pdf"}]}}
        openalex = {"doi": "https://doi.org/10.1234/example", "title": "A Deterministic Paper",
            "authorships": [{"author": {"display_name": "Katherine Johnson"}}], "publication_year": 2024,
            "primary_location": {"source": {"display_name": "Journal of Deterministic Tests"}},
            "best_oa_location": {"pdf_url": "https://papers.example/paper-openalex.pdf"}}
        def fetch(_url, _cache, provider):
            return crossref if provider == "crossref-doi" else openalex
        def curl(argv, **kwargs):
            destination = Path(argv[argv.index("--output") + 1])
            destination.write_bytes(b"%PDF-1.7 deterministic fixture")
            return subprocess.CompletedProcess(argv, 0, "", "")
        with (patch.object(scout_retrieval, "fetch_json", side_effect=fetch),
              patch.object(scout_retrieval.subprocess, "run", side_effect=curl),
              patch.object(scout_retrieval, "verify_pdf_text", return_value={"ok": True,
                    "first_page_text": "A Deterministic Paper Katherine Johnson", "reason": ""})):
            result = scout_retrieval.download_doi("10.1234/EXAMPLE", self.root / "papers", self.root / "cache")
        paper = result["paper"]
        target = self.root / "papers" / scout_retrieval._safe_doi_filename("10.1234/example")
        self.assertTrue(result["ok"])
        self.assertEqual(paper["doi"], "10.1234/example")
        self.assertEqual(paper["authors"], "Katherine Johnson")
        self.assertEqual(paper["year"], "2024")
        self.assertEqual(paper["venue"], "Journal of Deterministic Tests")
        self.assertEqual(Path(paper["download_path"]).resolve(), target.resolve())
        self.assertEqual(paper["sha256"], runner.sha256_file(target))
        self.assertTrue((self.root / "papers").joinpath(target.name).is_file())

    def test_selected_search_record_is_reused_for_doi_download(self):
        doi = "10.1234/cached-search"
        cache = self.root / "cache"
        crossref = [{"DOI": doi, "title": ["Cached topic search paper"],
                     "author": [{"given": "Test", "family": "Author"}],
                     "issued": {"date-parts": [[2024]]}, "container-title": ["Test Journal"],
                     "link": [{"content-type": "application/pdf", "URL": "https://papers.example/cached.pdf"}]}]
        with (patch.object(scout_retrieval, "search_crossref", return_value=crossref),
              patch.object(scout_retrieval, "search_openalex", return_value=[]),
              patch.object(scout_retrieval, "search_arxiv", return_value='<feed xmlns="http://www.w3.org/2005/Atom"/>')):
            candidates = scout_retrieval.search_topic("cached topic search", cache)
        self.assertEqual(candidates["papers"][0]["doi"], doi)
        def curl(argv, **kwargs):
            Path(argv[argv.index("--output") + 1]).write_bytes(b"%PDF-1.4 cached fixture")
            return subprocess.CompletedProcess(argv, 0, "", "")
        with (patch.object(scout_retrieval, "fetch_json", side_effect=AssertionError("unexpected network metadata lookup")),
              patch.object(scout_retrieval.subprocess, "run", side_effect=curl),
              patch.object(scout_retrieval, "verify_pdf_text", return_value={"ok": True, "first_page_text": "Cached topic search paper"})):
            result = scout_retrieval.download_doi(doi, self.root / "papers", cache)
        self.assertTrue(result["ok"])
        self.assertEqual(result["paper"]["doi"], doi)
        self.assertIn("download_path", result["paper"])

    def test_doi_download_rejects_incomplete_metadata_before_download(self):
        def fetch(_url, _cache, _provider):
            return {"message": {"DOI": "10.1234/example", "title": ["Title only"]}}
        with patch.object(scout_retrieval, "fetch_json", side_effect=fetch):
            with self.assertRaisesRegex(ValueError, "missing required metadata"):
                scout_retrieval.download_doi("10.1234/example", self.root / "papers", self.root / "cache")
        self.assertFalse((self.root / "papers").exists())

    def test_doi_download_rejects_invalid_pdf_and_leaves_no_partial_file(self):
        crossref = {"message": {"DOI": "10.1234/example", "title": ["A Deterministic Paper"],
            "author": [{"given": "Katherine", "family": "Johnson"}], "issued": {"date-parts": [[2024]]},
            "container-title": ["Journal of Deterministic Tests"],
            "link": [{"content-type": "application/pdf", "URL": "https://papers.example/paper.pdf"}]}}
        openalex = {"doi": "https://doi.org/10.1234/example", "title": "A Deterministic Paper",
            "authorships": [{"author": {"display_name": "Katherine Johnson"}}], "publication_year": 2024,
            "primary_location": {"source": {"display_name": "Journal of Deterministic Tests"}},
            "best_oa_location": {"pdf_url": "https://papers.example/paper-openalex.pdf"}}
        def fetch(_url, _cache, provider):
            return crossref if provider == "crossref-doi" else openalex
        def curl(argv, **kwargs):
            Path(argv[argv.index("--output") + 1]).write_bytes(b"not a PDF")
            return subprocess.CompletedProcess(argv, 0, "", "")
        with patch.object(scout_retrieval, "fetch_json", side_effect=fetch), \
             patch.object(scout_retrieval.subprocess, "run", side_effect=curl):
            with self.assertRaisesRegex(RuntimeError, "no PDF source passed verification"):
                scout_retrieval.download_doi("10.1234/example", self.root / "papers", self.root / "cache")
        self.assertEqual(list((self.root / "papers").iterdir()), [])

    def test_doi_downloader_caps_new_pdfs_at_five(self):
        papers = self.root / "papers"
        papers.mkdir()
        for number in range(5):
            (papers / f"old-{number}.pdf").write_bytes(b"%PDF-1.4 existing fixture")
        crossref = {"message": {"DOI": "10.1234/new", "title": ["New paper"],
            "author": [{"given": "Test", "family": "Author"}], "issued": {"date-parts": [[2024]]},
            "container-title": ["Test Journal"],
            "link": [{"content-type": "application/pdf", "URL": "https://papers.example/new.pdf"}]}}
        openalex = {"doi": "https://doi.org/10.1234/new", "title": "New paper",
            "authorships": [{"author": {"display_name": "Test Author"}}], "publication_year": 2024,
            "primary_location": {"source": {"display_name": "Test Journal"}},
            "best_oa_location": {"pdf_url": "https://papers.example/new-openalex.pdf"}}
        def fetch(_url, _cache, provider):
            return crossref if provider == "crossref-doi" else openalex
        with patch.object(scout_retrieval, "fetch_json", side_effect=fetch), \
             patch.object(scout_retrieval.subprocess, "run") as curl:
            result = scout_retrieval.download_doi("10.1234/new", papers, self.root / "cache")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "download_limit_reached")
        curl.assert_not_called()
        self.assertEqual(len(list(papers.glob("*.pdf"))), 5)

    def test_pdf_title_verification_tolerates_line_break_hyphenation(self):
        pdf = self.root / "fixture.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        for output in ("Sample-\nPolicy Planning\nKatherine Johnson\n" + ("first page text " * 8),
                       "SamplePartiallyObservableMarkovDecisionProcesses " + ("first page text " * 8)):
            proc = subprocess.CompletedProcess(["gs"], 0, output, "")
            with patch.object(scout_retrieval.subprocess, "run", return_value=proc):
                result = scout_retrieval.verify_pdf_text(pdf, "Sample partially observable Markov decision processes"
                                                       if "SamplePartially" in output
                                                       else "Sample Policy Planning")
            self.assertTrue(result["ok"])

    def test_writer_cannot_change_preamble_or_notation(self):
        main = self.run_dir / "Paper/Work-In-Progress/main.tex"
        original = main.read_text()
        changed = original.replace("fixed preamble", "changed preamble")
        main.write_text(changed)
        with self.assertRaisesRegex(runner.WorkflowError, "before the abstract"):
            runner.validate_manuscript_invariants(self.run_dir / "Paper", ["Work-In-Progress/main.tex"])
        main.write_text(original.replace("Keep this notation.", "Changed notation."))
        with self.assertRaisesRegex(runner.WorkflowError, "Notation"):
            runner.validate_manuscript_invariants(self.run_dir / "Paper", ["Work-In-Progress/main.tex"])

    def test_controller_stamps_handoff_provenance_and_duplicate_json_keys(self):
        job = runner._agent_job(self.config, "test-run", self.run_dir, "A-Scout", 1, self.paper_hash)
        keys = ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")
        payload = {"status": "ok", "summary": "test", "paper_sha256": "stale",
                   "input_hashes": {"wrong": "hash"}}
        runner.validate_envelope(payload, job)
        for key in keys:
            self.assertEqual(payload[key], job[key])
        legacy = {"status": "ok", "summary": "legacy", "envelope": {"paper_sha256": "stale"}}
        runner.validate_envelope(legacy, job)
        self.assertNotIn("envelope", legacy)
        self.assertEqual(legacy["paper_sha256"], job["paper_sha256"])
        with self.assertRaises(ValueError):
            runner.load_json_from_text('{"x":1,"x":2}')
        latex = runner._loads_model_json(r'{"proof":"t=\st+1, \text{x}, \frac{a}{b}"}')
        self.assertEqual(latex["proof"], r"t=\st+1, \text{x}, \frac{a}{b}")
        multiline = runner._loads_model_json(r'{"proof":"line one\n line two"}')
        self.assertEqual(multiline["proof"], "line one\n line two")
        with self.assertRaisesRegex(ValueError, "unsupported control"):
            runner._loads_model_json(r'{"proof":"bad\u0001text"}')

    def test_version_snapshot_preserves_all_files_and_advances_from_v4(self):
        project = self.root / "project"
        project.mkdir()
        for old in range(1, 5):
            (project / "AI-Versions" / f"V{old}").mkdir(parents=True)
        (project / "Paper").mkdir()
        for relative, digest in self.initial.items():
            target = project / "Paper" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative.endswith("main.pdf"):
                target.write_bytes(b"%PDF-1.4 baseline")
            else:
                source = self.run_dir / "Paper" / relative
                target.write_bytes(source.read_bytes())
        # Mirror the synthetic run under the temporary project before finalization.
        local_run = project / "Agent-Outputs/runs/test-run"
        shutil = __import__("shutil")
        shutil.copytree(self.run_dir, local_run)
        main = local_run / "Paper/Work-In-Progress/main.tex"
        main.write_text(main.read_text().replace("Baseline result.", r"\writerrevision{Versioned result.}"))
        (local_run / "Paper/Work-In-Progress/main.pdf").write_bytes(b"%PDF-1.4 new")
        local_manifest = runner.tree_manifest(local_run / "Paper")
        changed = [p for p in local_manifest if self.initial.get(p) != local_manifest[p]]
        writer = {"summary": "Synthetic version", "changed_files": ["Work-In-Progress/main.tex"]}
        result = {"researcher": {"ideas": [{"id": "I1"}]}, "writer": writer,
                  "build": {"normal_pdf_sha256": runner.sha256_file(local_run / "Paper/Work-In-Progress/main.pdf")}}
        config = copy.deepcopy(self.config)
        with patch.object(runner, "ROOT", project):
            version = runner.commit_and_archive(config, "test-run", local_run, self.initial, result)
        self.assertEqual(version, "V5")
        self.assertTrue((project / "AI-Versions/V5/Paper/Work-In-Progress/main.pdf").is_file())
        self.assertTrue((project / "AI-Versions/version.md").is_file())
        self.assertIn("V5", (project / "AI-Versions/version.md").read_text())


if __name__ == "__main__":
    unittest.main()
