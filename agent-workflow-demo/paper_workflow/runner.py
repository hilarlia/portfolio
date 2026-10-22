#!/usr/bin/env python3
"""Deterministic controller for the direct manuscript-improvement and post-Writer feedback workflow.

Agents run in fresh Pi sessions through the project's Nono isolated launcher.
Only JSON handoffs cross role boundaries; the controller owns routing, budgets,
validation, compilation, publication, and version snapshots.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import fcntl
import hashlib
import json
import math
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

try:
    from paper_workflow import scout_retrieval
except ModuleNotFoundError:  # direct script execution via workflow
    import scout_retrieval

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "agent-workflow.json"
AGENT_ORDER = ("A-Scout", "A-Researcher", "A-Writer", "A-Correcter")
STANDALONE_ROLES = ()
MAX_RESEARCHER_COMMENTS_BYTES = 4000
CORRECTER_PRIOR_FEEDBACK = "Agent-Outputs/A-Correcter/Prior-Feedback.json"
OUTPUT_FILES = {
    "A-Scout": "Agent-Outputs/A-Scout/Overview.json",
    "A-Researcher": "Agent-Outputs/A-Researcher.json",
    "A-Writer": "Agent-Outputs/A-Writer.json",
    "A-Correcter": "Agent-Outputs/A-Correcter/Feedback.json",
}
AUX_SUFFIXES = {".aux", ".log", ".fls", ".fdb_latexmk", ".blg", ".bbl", ".out", ".toc", ".dvi", ".synctex", ".gz"}
WRITER_FILES = (
    "Work-In-Progress/main.tex",
    "Work-In-Progress/LatexInclusion/Local-Introduction.tex",
    "Work-In-Progress/LatexInclusion/Local-Definitions.tex",
    "Work-In-Progress/LatexInclusion/Local-Temp.bib",
    "Work-In-Progress/LatexInclusion/Local-Acronyms.tex",
)


class WorkflowError(RuntimeError):
    """An actionable, fail-closed workflow error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid JSON number {value}")))


def write_json(path: Path, value, *, compact=False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    text = json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":") if compact else None,
                      indent=None if compact else 2, sort_keys=False) + "\n"
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_fingerprint(paper: dict) -> str:
    doi = str(paper.get("doi", "")).strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    if doi:
        return "doi:" + doi
    url = str(paper.get("url", "")).strip().rstrip("/").lower()
    return "url:" + url if url else ""


def _all_scout_sources(run_dir: Path) -> dict:
    """Return the validated Scout overview as the Researcher's source universe."""
    overview = load_json(run_dir / OUTPUT_FILES["A-Scout"])
    for item in overview.get("papers", []):
        paper_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(paper_id, str) or not paper_id:
            raise WorkflowError("Scout Overview contains a missing source ID")
    return overview


def _ignored(relative: Path) -> bool:
    return (any(part in {".git", ".venv", "__pycache__"} for part in relative.parts)
            or relative.name == ".DS_Store"
            or relative.suffix.lower() in AUX_SUFFIXES)


def tree_manifest(root: Path) -> dict[str, str]:
    """Hash regular files only; reject links instead of following them."""
    if not root.is_dir():
        raise WorkflowError(f"Required directory is missing: {root}")
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _ignored(relative):
            continue
        if path.is_symlink():
            raise WorkflowError(f"Symlinks are not allowed in the paper tree: {path}")
        if path.is_file():
            result[relative.as_posix()] = sha256_file(path)
    return result


def manifest_hash(manifest: dict[str, str]) -> str:
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise WorkflowError("Run ID must be 1-80 letters/digits/hyphens/underscores, starting alphanumeric")
    return value


def load_config(path: Path = CONFIG_FILE) -> dict:
    config = load_json(path)
    if config.get("schema_version") != 1:
        raise WorkflowError("Unsupported agent-workflow.json schema_version")
    if tuple(config.get("roles", {}).keys()) != AGENT_ORDER:
        raise WorkflowError("The full-run roles must be Scout, Researcher, and Writer in that order")
    if tuple(config.get("standalone_roles", {}).keys()) != STANDALONE_ROLES:
        raise WorkflowError("No standalone roles are configured; A-Correcter is a post-Writer full-run stage")
    limits = config.get("limits", {})
    for name in ("stage_timeout_sec", "preflight_timeout_sec", "build_timeout_sec",
                 "max_stream_bytes", "max_artifact_bytes",
                 "max_ideas", "max_papers",
                 "max_paper_bytes", "max_total_download_bytes",
                 "max_total_input_tokens", "max_total_output_tokens"):
        if type(limits.get(name)) is not int or limits[name] <= 0:
            raise WorkflowError(f"limits.{name} must be a positive integer")
    name = "max_scout_retries"
    if type(limits.get(name)) is not int or limits[name] < 0:
        raise WorkflowError(f"limits.{name} must be a nonnegative integer")
    if limits[name] > 1:
        raise WorkflowError("At most one Scout retrieval retry is permitted")
    budget = limits.get("max_cost_usd")
    if not isinstance(budget, (int, float)) or budget <= 0:
        raise WorkflowError("limits.max_cost_usd must be positive")
    resume_extra = limits.get("max_resume_extra_cost_usd", 0)
    if not isinstance(resume_extra, (int, float)) or resume_extra < 0:
        raise WorkflowError("limits.max_resume_extra_cost_usd must be nonnegative")
    for role, settings in {**config["roles"], **config["standalone_roles"]}.items():
        model = settings.get("model", "")
        if not model.startswith(("example-provider/openai/", "example-provider/bedrock/")):
            raise WorkflowError(f"{role}: model must be an exact Example Provider OpenAI or Bedrock catalog ID")
        if settings.get("thinking") not in {"minimal", "low", "medium", "high", "xhigh"}:
            raise WorkflowError(f"{role}: unsupported thinking level")
        if type(settings.get("max_output_tokens")) is not int or not 1000 <= settings["max_output_tokens"] <= 80000:
            raise WorkflowError(f"{role}: max_output_tokens must be between 1000 and 80000")
    writer_files = config.get("writer_files", [])
    required_files = set(WRITER_FILES)
    if set(writer_files) != required_files:
        raise WorkflowError("Writer's allowlist must match the five explicit manuscript files")
    return config


def run_lock(outputs: Path):
    outputs.mkdir(parents=True, exist_ok=True)
    lock_path = outputs / ".workflow.lock"
    stream = lock_path.open("a+")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        stream.close()
        raise WorkflowError("Another paper workflow run is active") from exc
    return stream


def next_version(versions: Path) -> str:
    numbers = []
    if versions.exists():
        for path in versions.iterdir():
            match = re.fullmatch(r"V(\d+)", path.name)
            if match and path.is_dir():
                numbers.append(int(match.group(1)))
    return f"V{max(numbers, default=0) + 1}"


def role_policy(role: str, run_outputs: Path | None = None, round_number: int = 1) -> dict:
    """Return small, explicit read/write scopes for the named specialist."""
    read = []
    write = []
    main_tex = "Paper/Work-In-Progress/main.tex"
    main_pdf = "Paper/Work-In-Progress/main.pdf"
    scout_dir = "Agent-Outputs/A-Scout"
    researcher_file = "Agent-Outputs/A-Researcher.json"
    writer_file = "Agent-Outputs/A-Writer.json"
    researcher_feedback_available = False
    if role == "A-Scout":
        read = [main_tex, main_pdf, "scout_retrieval.py",
                f"{scout_dir}/Read-Papers.json", f"{scout_dir}/papers"]
        if run_outputs is not None and (run_outputs / f"{scout_dir}/Overview.json").is_file():
            read.append(f"{scout_dir}/Overview.json")
        if round_number > 1:
            read.append(f"{scout_dir}/Overview.json")
        write = [f"{scout_dir}/papers"]
    elif role == "A-Researcher":
        read = [main_tex, main_pdf, "Paper/Work-In-Progress/LatexInclusion/Local-Introduction.tex",
                "Paper/Work-In-Progress/LatexInclusion/Local-Definitions.tex",
                f"{scout_dir}/Overview.json", f"{scout_dir}/Read-Papers.json",
                "scout_retrieval.py"]
        feedback_path = run_outputs / CORRECTER_PRIOR_FEEDBACK if run_outputs is not None else None
        if feedback_path is not None and feedback_path.is_file():
            try:
                prior_feedback = load_json(feedback_path)
            except (OSError, ValueError):
                prior_feedback = {}
            researcher_feedback_available = (prior_feedback.get("status") == "ok"
                                             and bool(prior_feedback.get("feedback")))
            if researcher_feedback_available:
                read.append(CORRECTER_PRIOR_FEEDBACK)
        if round_number > 1:
            read.append(researcher_file)
    elif role == "A-Writer":
        read = ["Paper", scout_dir, researcher_file,
                "skills/skills-paper_writing.md", "skills/skills-paper_citation.md",
                "skills/BetterBibTeX-preferences.json"]
        write = [f"Paper/{relative}" for relative in WRITER_FILES]
    elif role == "A-Correcter":
        read = ["Paper", "source-writer-files", scout_dir, researcher_file, writer_file,
                "scout_retrieval.py", "skills/skills-paper_writing.md", "skills/skills-paper_citation.md",
                "skills/BetterBibTeX-preferences.json"]
        write = []
    else:
        raise WorkflowError(f"Unknown role: {role}")
    # Only pass inputs that exist. The preflight creates harmless placeholders so
    # each profile can be checked before the first paid agent stage.
    if run_outputs is not None:
        read = [item for item in read if (run_outputs / item).exists()]
    network = ("none" if role == "A-Researcher" and not researcher_feedback_available
               else "approved-public-search-and-source-read")
    if role == "A-Researcher":
        tools = ["read", "grep", "bash"] if researcher_feedback_available else ["read", "grep"]
    elif role == "A-Correcter":
        tools = ["read", "grep", "bash"]
    else:
        tools = ["read", "grep", "find", "ls", "bash"]
    if role in {"A-Scout", "A-Writer"}:
        tools.append("write")
    if role == "A-Writer":
        tools.append("edit")
    return {"read_only": read, "write": write, "network": network, "tools": tools}


def input_hashes(run_dir: Path, paths: list[str]) -> dict[str, str]:
    result = {}
    for relative in paths:
        target = run_dir / relative
        if target.is_symlink() or not target.exists():
            raise WorkflowError(f"Declared agent input is missing or a symlink: {relative}")
        if target.is_file():
            result[relative] = sha256_file(target)
        elif target.is_dir():
            result[relative] = manifest_hash(tree_manifest(target))
        else:
            raise WorkflowError(f"Declared input is not a regular file/directory: {relative}")
    return result


def _agent_job(config: dict, run_id: str, run_dir: Path, role: str, round_number: int,
               paper_hash: str, *, preflight=False, research_brief="", researcher_comments="") -> dict:
    policy = role_policy(role, run_dir, round_number)
    if preflight:
        hashes = {}
    else:
        hashes = input_hashes(run_dir, policy["read_only"])
    role_cfg = config["roles"].get(role) or config["standalone_roles"][role]
    limits = config["limits"]
    job = {
        "schema_version": 1,
        "run_id": run_id,
        "agent": role,
        "stage": role,
        "round": round_number,
        "paper_sha256": paper_hash,
        "input_hashes": hashes,
        "research_brief": research_brief,
        "researcher_comments": researcher_comments if role in {"A-Scout", "A-Researcher", "A-Writer"} else "",
        "model": {"model": role_cfg["model"], "thinking": role_cfg["thinking"]},
        "permissions": policy,
        "limits": {
            "stage_timeout_sec": limits["stage_timeout_sec"],
            "max_output_tokens": role_cfg["max_output_tokens"],
            "max_stream_bytes": limits["max_stream_bytes"],
            "max_artifact_bytes": limits["max_artifact_bytes"],
            "max_check_operators": 1000,
            "max_check_seconds": 60,
            "per_tool_timeout_sec": 300,
        },
    }
    if role == "A-Writer":
        job["writer_comments_version"] = 1
    return job


def _checkpoint_path(run_dir: Path, role: str, round_number: int) -> Path:
    return run_dir / "checkpoints" / f"before-{role}-r{round_number}.json"


def _write_completion_checkpoint(run_dir: Path, job: dict, prompt: str, payload: dict, metrics: dict) -> Path:
    role = job["agent"]
    path = run_dir / "checkpoints" / f"after-{role}-r{job['round']}.json"
    checkpoint = {
        "schema_version": 1,
        "checkpoint_type": "agent_completion",
        "run_id": job["run_id"],
        "agent": role,
        "round": job["round"],
        "created_at": utc_now(),
        "paper_sha256": job["paper_sha256"],
        "job_sha256": hashlib.sha256(json.dumps(job, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "input_hashes": job.get("input_hashes", {}),
        "output_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
        "metrics": copy.deepcopy(metrics),
    }
    write_json(path, checkpoint)
    return path


def _write_stage_checkpoint(run_dir: Path, job: dict, prompt: str, metrics: dict) -> Path:
    role = job["agent"]
    if role not in {"A-Researcher", "A-Writer"}:
        raise WorkflowError(f"Checkpoints are not configured for {role}")
    path = _checkpoint_path(run_dir, role, job["round"])
    checkpoint = {
        "schema_version": 1,
        "run_id": job["run_id"],
        "next_stage": role,
        "round": job["round"],
        "created_at": utc_now(),
        "paper_sha256": job["paper_sha256"],
        "job": job,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "metrics_before_stage": dict(metrics),
    }
    write_json(path, checkpoint)
    return path


def _validate_stage_checkpoint(run_dir: Path, checkpoint: dict, status: dict) -> tuple[dict, str]:
    if checkpoint.get("schema_version") != 1 or checkpoint.get("run_id") != status.get("run_id"):
        raise WorkflowError("Resume checkpoint schema/run ID does not match the failed run")
    job = checkpoint.get("job")
    role = checkpoint.get("next_stage")
    round_number = checkpoint.get("round")
    if not isinstance(job, dict):
        raise WorkflowError("Resume checkpoint has no valid saved job")
    if role not in {"A-Researcher", "A-Writer"} or type(round_number) is not int or round_number < 1:
        raise WorkflowError("Resume checkpoint does not identify a supported Researcher or Writer stage")
    if job.get("agent") != role or job.get("round") != round_number:
        raise WorkflowError("Resume checkpoint stage does not match its saved job")
    if checkpoint.get("paper_sha256") != status.get("paper_sha256") or job.get("paper_sha256") != status.get("paper_sha256"):
        raise WorkflowError("Resume checkpoint manuscript snapshot hash does not match the run")
    if role == "A-Researcher" and job.get("researcher_comments", "") != status.get("researcher_comments", ""):
        raise WorkflowError("Resume checkpoint Researcher comments do not match the run record")
    if (role == "A-Writer" and job.get("writer_comments_version") == 1
            and job.get("researcher_comments", "") != status.get("researcher_comments", "")):
        raise WorkflowError("Resume checkpoint Writer comments do not match the run record")
    job_path = run_dir / "jobs" / f"{role}-r{round_number}.json"
    prompt_path = run_dir / "jobs" / f"{role}-r{round_number}.md"
    if not job_path.is_file() or not prompt_path.is_file():
        raise WorkflowError("Resume checkpoint job or prompt is missing/changed")
    saved_job = load_json(job_path)
    if saved_job != job:
        saved_without_limits = {key: value for key, value in saved_job.items() if key != "limits"}
        checkpoint_without_limits = {key: value for key, value in job.items() if key != "limits"}
        if saved_without_limits != checkpoint_without_limits:
            raise WorkflowError("Resume checkpoint job or prompt is missing/changed")
        job["limits"] = saved_job.get("limits", job.get("limits", {}))
    # Prompt revisions are allowed during an explicit recovery; manuscript,
    # checkpoint input hashes, and the saved job remain immutable bindings.
    expected_inputs = job.get("input_hashes")
    if not isinstance(expected_inputs, dict) or input_hashes(run_dir, list(expected_inputs)) != expected_inputs:
        raise WorkflowError("Resume checkpoint input hashes no longer match the run artifacts")
    source_manifest = load_json(run_dir / "source.manifest.json")
    if manifest_hash(source_manifest) != status.get("paper_sha256"):
        raise WorkflowError("Resume source manifest does not match its recorded manuscript hash")
    if manifest_hash(tree_manifest(run_dir / "Paper")) != status.get("paper_sha256"):
        raise WorkflowError("Run manuscript snapshot changed after the checkpoint")
    return job, prompt_path.read_text(encoding="utf-8")


def _writer_build_failure(status: dict) -> bool:
    failed = status.get("failed_stage") or {}
    if failed.get("agent") != "A-Writer":
        return False
    history = status.get("history", [])
    build_indexes = [index for index, event in enumerate(history)
                     if event.get("agent") == "A-Writer" and event.get("state") == "building"]
    failure_indexes = [index for index, event in enumerate(history)
                       if event.get("agent") == "A-Writer" and event.get("state") == "failed"]
    return bool(build_indexes and failure_indexes and max(build_indexes) < max(failure_indexes))


def _checkpointed_writer_payload_from_log(run_dir: Path, job: dict, checkpoint: dict) -> dict:
    log_path = run_dir / "logs/A-Writer-r1.jsonl"
    if not log_path.is_file() or log_path.is_symlink():
        raise WorkflowError("Missing Writer output artifact and trustworthy completion log for build recovery")
    envelope_keys = ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")
    expected_digest = checkpoint.get("output_sha256")
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("message")
        if event.get("type") != "message_end" or not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for part in message.get("content", []):
            if part.get("type") != "text":
                continue
            try:
                response = load_json_from_text(part.get("text", ""))
            except ValueError:
                continue
            if not isinstance(response, dict):
                continue
            payload = dict(response)
            payload.pop("envelope", None)
            for key in envelope_keys:
                payload.pop(key, None)
                payload[key] = job[key]
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            if digest == expected_digest:
                return payload
    raise WorkflowError("No Writer response in the saved log matches the validated completion-checkpoint digest")


def _load_writer_build_recovery(config: dict, run_dir: Path, status: dict) -> tuple[dict, str, dict]:
    """Load an already-validated Writer result after a build failure, without rerunning the model."""
    job_path = run_dir / "jobs/A-Writer-r1.json"
    prompt_path = run_dir / "jobs/A-Writer-r1.md"
    checkpoint_path = run_dir / "checkpoints/after-A-Writer-r1.json"
    for path in (job_path, prompt_path, checkpoint_path):
        if not path.is_file() or path.is_symlink():
            raise WorkflowError(f"Writer build recovery artifact is missing or unsafe: {path.name}")
    job = load_json(job_path)
    prompt = prompt_path.read_text(encoding="utf-8")
    checkpoint = load_json(checkpoint_path)
    if (checkpoint.get("schema_version") != 1 or checkpoint.get("checkpoint_type") != "agent_completion"
            or checkpoint.get("run_id") != status.get("run_id") or checkpoint.get("agent") != "A-Writer"
            or checkpoint.get("round") != 1 or checkpoint.get("paper_sha256") != status.get("paper_sha256")):
        raise WorkflowError("Writer build-recovery completion checkpoint does not match the failed run")
    job_digest = hashlib.sha256(json.dumps(job, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if (job.get("agent") != "A-Writer" or job.get("run_id") != status.get("run_id")
            or job.get("paper_sha256") != status.get("paper_sha256")
            or checkpoint.get("job_sha256") != job_digest
            or checkpoint.get("prompt_sha256") != hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            or checkpoint.get("input_hashes") != job.get("input_hashes")):
        raise WorkflowError("Writer build-recovery job or prompt does not match its completion checkpoint")
    job_inputs = job.get("input_hashes")
    if not isinstance(job_inputs, dict) or job_inputs.get("Paper") != status.get("paper_sha256"):
        raise WorkflowError("Writer completion checkpoint is not bound to the original Paper snapshot")
    other_inputs = {path: digest for path, digest in job_inputs.items() if path != "Paper"}
    if input_hashes(run_dir, list(other_inputs)) != other_inputs:
        raise WorkflowError("A declared non-Paper Writer input changed after the completed Writer stage")
    source_manifest = load_json(run_dir / "source.manifest.json")
    paper_path = ROOT / config["paths"]["paper"]
    if (manifest_hash(source_manifest) != status.get("paper_sha256")
            or manifest_hash(tree_manifest(paper_path)) != status.get("paper_sha256")):
        raise WorkflowError("Live manuscript no longer matches the original failed-run snapshot")

    handoff_path = run_dir / OUTPUT_FILES["A-Writer"]
    payload = None
    if handoff_path.is_file() and not handoff_path.is_symlink():
        try:
            candidate = load_json(handoff_path)
            digest = hashlib.sha256(json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            if digest == checkpoint.get("output_sha256"):
                payload = candidate
        except (OSError, ValueError, TypeError):
            pass
    if payload is None:
        payload = _checkpointed_writer_payload_from_log(run_dir, job, checkpoint)

    validate_envelope(payload, job)
    validate_agent_payload("A-Writer", payload, run_dir, config)
    current_manifest = tree_manifest(run_dir / "Paper")
    initial_manifest = _initial_manifest(run_dir)
    changed = sorted(path for path in set(initial_manifest) | set(current_manifest)
                     if initial_manifest.get(path) != current_manifest.get(path))
    built_pdf = "Work-In-Progress/main.pdf"
    manuscript_changes = [path for path in changed if path != built_pdf]
    if (not manuscript_changes or not set(changed) <= set(config["writer_files"]) | {built_pdf}
            or not set(manuscript_changes) <= set(config["writer_files"])):
        raise WorkflowError("Writer build-recovery Paper diff is empty or outside the Writer/build allowlists")
    if set(payload.get("changed_files", [])) != set(manuscript_changes):
        raise WorkflowError("Writer build-recovery changed_files does not match the current manuscript diff")
    validate_manuscript_invariants(run_dir / "Paper", manuscript_changes)
    write_json(handoff_path, payload)
    return job, prompt, payload


def _prompt(config: dict, role: str, job: dict, run_dir: Path, prior_error: str = "") -> str:
    source = ROOT / "agents" / "prompts" / f"{role}.md"
    if not source.is_file():
        raise WorkflowError(f"Missing role prompt: {source}")
    envelope = {key: job[key] for key in
                ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")}
    limit = config["limits"]["max_artifact_bytes"]
    extra = ""
    if role == "A-Scout" and job["round"] == 1 and "Agent-Outputs/A-Scout/Overview.json" in job["permissions"]["read_only"]:
        extra = ("\nA previous complete Scout Overview and its source PDFs are supplied from an incomplete earlier run. "
                 "Verify/reuse these stable source IDs and local files first; do not redownload an existing PDF. "
                 "Keep exactly the declared files in the papers folder, or remove any replaced file before returning. "
                 "Update source metadata/locators only when you can verify the correction.\n")
    if role == "A-Scout" and job["round"] > 1:
        extra = ("\nThis is the one permitted retrieval repair. Read your previous Overview.json, retain verified source IDs, "
                 "reuse already downloaded PDFs in the declared papers folder, replace weak/unverified entries, and download missing accessible PDFs. "
                 "Use the granted bash/curl tool; use `python3` rather than `python`, and do not use non-portable awk. "
                 "Return status=ok only when the requested source bundle is complete; otherwise return status=partial with precise blockers.\n")
    if role == "A-Scout":
        comments = job.get("researcher_comments", "").strip()
        if comments:
            extra += ("\nUser comments for this full run (research guidance, not evidence):\n"
                      "<user-comments>\n" + comments + "\n</user-comments>\n"
                      "If these comments describe a research request, identify the field, topic, subtopics, methods, and any stated date/source constraints. Turn the relevant details into focused search terms and prioritize them within the finite search plan; use no more than three comment-focused queries, replacing default topics where appropriate. Download papers only through the normal verified retrieval flow. If the comments are empty or contain no research topic, use the existing manuscript-derived search plan unchanged. Comments and references in them are not evidence and must be verified independently; they do not override source relevance, transfer limits, output/download caps, metadata/provenance checks, permissions, or other workflow rules.\n")
    if role == "A-Researcher":
        extra = ("\nResearch brief: " + job.get("research_brief", "") + "\n"
                 "There is no candidate plan or novelty-screen stage. Consider the manuscript directly and forward every supported correction, scope clarification, modest incremental development, and new result. Do not reject or omit a useful idea because it is not novel; describe prior work and limitations factually, but novelty is not an acceptance condition.\n")
        comments = job.get("researcher_comments", "").strip()
        if comments:
            extra += ("\nUser comments for this full run (guidance, not evidence):\n"
                      "<user-comments>\n" + comments + "\n</user-comments>\n"
                      "Address these priorities where they fit the manuscript and available evidence. These comments do not override source/provenance requirements, workflow rules, or your obligation to verify factual claims.\n")
    if role == "A-Writer":
        comments = job.get("researcher_comments", "").strip()
        if comments:
            extra += ("\nUser comments for this full run (writing guidance, not evidence):\n"
                      "<user-comments>\n" + comments + "\n</user-comments>\n"
                      "Use these notes as additional context only where they fit the validated Researcher handoff and verified sources. They are not evidence: do not add unsupported claims/citations and do not omit supported Researcher ideas. Do not override allowed-file, manuscript-invariant, revision-markup, or isolated-build requirements.\n")
    if role == "A-Researcher" and job["round"] > 1:
        extra += ("\nResearch brief: " + job.get("research_brief", "") + "\n"
                  "Your prior output is in the declared inputs. Make only evidence-supported changes.\n")
    if role == "A-Researcher" and (run_dir / CORRECTER_PRIOR_FEEDBACK).is_file():
        try:
            prior_feedback = load_json(run_dir / CORRECTER_PRIOR_FEEDBACK)
        except (OSError, ValueError):
            prior_feedback = {}
        if prior_feedback.get("status") == "ok" and prior_feedback.get("feedback"):
            extra += ("\nA-Correcter feedback from the prior Writer run is mounted read-only at "
                      + CORRECTER_PRIOR_FEEDBACK + ". Treat it as exploratory leads, not conclusions or gates. "
                      "Try to investigate and incorporate relevant suggestions. For technique names, use up to three focused "
                      "`python3 scout_retrieval.py search-topic '<query>' --no-cache` calls and consult public metadata/abstracts as needed. "
                      "Do not reject ordinary corrections or ideas if a feedback lead is irrelevant.\n")
    if prior_error:
        extra += "\nPrevious bounded validation feedback (fix only these format/contract issues):\n" + prior_error[:1500] + "\n"
    if role == "A-Researcher":
        scout_path = run_dir / "Agent-Outputs/A-Scout/Overview.json"
        index_path = run_dir / "Agent-Outputs/A-Scout/Read-Papers.json"
        if scout_path.is_file() and index_path.is_file():
            scout_sources = _all_scout_sources(run_dir).get("papers", [])
            indexed = {item.get("id") for item in load_json(index_path).get("papers", []) if isinstance(item, dict)}
            prior_ids = [item["id"] for item in scout_sources if item["id"] in indexed]
            extra += ("\nResearcher source-use scope: current-run PDFs are handled by A-Scout, not this role. "
                      "Do not attempt network searches or new-PDF extraction; use relevant indexed findings from Read-Papers.json and cite only IDs from the current prior-ID list. "
                      "Allowed prior_papers_reused IDs from Read-Papers.json (use only a relevant subset): " + json.dumps(prior_ids) + ". This is the complete allowed list. Do not include IDs that appear only in the current Scout Overview; they are not previously read/indexed sources. Return papers_read as [] exactly because Scout owns current-run PDF reading. "
                      + "Source/provenance checks still apply; novelty is not an acceptance test.\n")
    example = {"status": "ok", "summary": "Replace with your actual concise summary."}
    role_response_fields = {
        "A-Scout": "papers, techniques, queries, limitations",
        "A-Researcher": "ideas, impact_map, narrative_plan, papers_read, prior_papers_reused, no_idea_reason",
        "A-Writer": "integrated_idea_ids, changed_files, unresolved",
        "A-Correcter": "feedback, queries, limitations",
    }[role]
    return (source.read_text(encoding="utf-8") + extra
            + "\n## This job\n"
            + json.dumps({"envelope": envelope, "read_only": job["permissions"]["read_only"],
                          "write": job["permissions"]["write"], "limits": job["limits"]},
                         ensure_ascii=False, separators=(",", ":"))
            + "\n\n## Required response shape (top-level role payload)\n"
            + "The envelope in the job is input metadata only. Do NOT echo or nest schema_version, run_id, agent, round, paper_sha256, or input_hashes; the trusted controller stamps those onto the saved handoff. "
            + "Return status, summary, and these role fields as top-level keys: " + role_response_fields + ".\n"
            + "The small shape example below is not a complete response. Replace its summary placeholder and include every required role field from your role prompt.\n"
            + json.dumps(example, ensure_ascii=False, separators=(",", ":"))
            + "\n\n## Handoff contract\n"
            + "Return exactly one JSON object with only your role's top-level result fields; never add an `envelope` wrapper or copy job metadata. "
            + "Keep the output under " + str(limit) + " UTF-8 bytes. Use valid JSON escapes; proof/patch strings may contain escaped \\n line breaks. Escape every LaTeX backslash as `\\\\` in the raw JSON. Cite source IDs/locations, not copied source text. "
            + "Do not emit chain-of-thought, hidden reasoning, tool transcripts, Markdown fences, or additional text.\n")


def _latest_pi_runtime() -> tuple[Path, Path]:
    install = Path.home() / ".pi/agent/install/releases"
    candidates = list(install.glob("*/node_modules/@earendil-works/pi-coding-agent"))
    if not candidates:
        raise WorkflowError("Pi managed runtime not found under ~/.pi/agent/install/releases")
    def version_key(path):
        match = re.search(r"releases/([^/]+)/", path.as_posix())
        return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", match.group(1))) if match else ()
    package = max(candidates, key=version_key).resolve()
    cli = package / "dist/bundle/cli.js"
    if not cli.is_file():
        raise WorkflowError(f"Pi CLI bundle is missing: {cli}")
    return package, cli


def _runtime_args(config: dict) -> tuple[list[str], dict[str, Path]]:
    paths = config["paths"]
    nono = shutil.which("nono") or str(Path.home() / ".local/bin/nono")
    nono = Path(nono).resolve()
    profile = Path.home() / ".config/nono/profiles/mit-example-provider.json"
    node = shutil.which("node")
    node_path = Path(node).resolve() if node else Path.home() / ".local/share/pi-node/current/bin/node"
    pi_package, pi_cli = _latest_pi_runtime()
    extension = Path.home() / ".pi/agent/npm/node_modules/mit-example-provider-pi-extension"
    jiti = pi_package.parent.parent / "jiti"
    python = Path(sys.executable).resolve()
    python_root = python.parent.parent
    tex = shutil.which("latexmk")
    kpsewhich = shutil.which("kpsewhich")
    launcher = ROOT / paths["nono_launcher"]
    required = {"nono": nono, "nono profile": profile, "node": node_path,
                "Pi CLI": pi_cli, "Pi package": pi_package, "Example Provider extension": extension,
                "jiti": jiti, "Python": python, "Nono launcher": launcher}
    missing = [f"{label}: {path}" for label, path in required.items() if not path.exists()]
    if not tex or not Path(tex).is_file():
        missing.append("TeX latexmk: not found on PATH")
    if missing:
        raise WorkflowError("Runtime preflight missing required components:\n  " + "\n  ".join(missing))
    if not os.environ.get("EXAMPLE_PROVIDER_API_KEY"):
        raise WorkflowError("EXAMPLE_PROVIDER_API_KEY is not set in this shell; no agent was started and no credentials are stored by the workflow")
    # Keep TeX's shim directory in PATH: resolving the latexmk symlink here
    # points at texmf-dist/scripts/latexmk and hides pdflatex/bibtex.
    tex_bin = Path(tex).absolute().parent
    if kpsewhich:
        probe = subprocess.run([kpsewhich, "--var-value=TEXMFROOT"], capture_output=True, text=True, timeout=10)
        tex_root = Path(probe.stdout.strip()) if probe.returncode == 0 and probe.stdout.strip() else tex_bin.parent
    else:
        tex_root = tex_bin.parent
    values = {
        "nono": nono, "profile": profile, "node": node_path,
        "pi_cli": pi_cli, "pi_package": pi_package, "extension": extension,
        "jiti": jiti, "python": python, "python_root": python_root,
        "tex_bin": tex_bin, "tex_root": tex_root,
        "latexmk": Path(tex).resolve(), "launcher": launcher,
    }
    argv = [
        str(python), str(launcher), "--nono", str(nono),
        "--profile-source", str(profile), "--profile-sha256", sha256_file(profile),
        "--nono-sha256", sha256_file(nono), "--node", str(node_path),
        "--node-sha256", sha256_file(node_path), "--pi-cli", str(pi_cli),
        "--pi-cli-sha256", sha256_file(pi_cli), "--pi-package", str(pi_package),
        "--pi-package-sha256", _sha_tree(pi_package), "--example-provider-extension", str(extension),
        "--example-provider-extension-sha256", _sha_tree(extension), "--python-bin", str(python),
        "--python-bin-sha256", sha256_file(python), "--python-root", str(python_root),
        "--jiti-package", str(jiti), "--tex-bin", str(tex_bin), "--tex-root", str(tex_root),
        "--latexmk", str(Path(tex).resolve()), "--latexmk-sha256", sha256_file(Path(tex).resolve()),
    ]
    return argv, values


def _sha_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise WorkflowError(f"Symlink in pinned runtime dependency tree: {path}")
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _descendants(root_pid: int) -> list[int]:
    try:
        result = subprocess.run(["ps", "-e", "-o", "pid=", "-o", "ppid="],
                                capture_output=True, text=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        try:
            pid, parent = map(int, line.split())
        except ValueError:
            continue
        children.setdefault(parent, []).append(pid)
    found = []
    stack = [root_pid]
    while stack:
        for child in children.get(stack.pop(), []):
            found.append(child)
            stack.append(child)
    return found


def _kill_process_tree(process: subprocess.Popen) -> None:
    for pid in reversed(_descendants(process.pid)):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _run_bounded(argv: list[str], *, cwd: Path, timeout: int, byte_limit: int,
                 stdout_path: Path, stderr_path: Path, on_event: Callable | None = None,
                 per_tool_timeout_sec: int | None = None,
                 label: str = "stage") -> tuple[int, str]:
    """Stream and bound a child process; stdin is closed and detached descendants are killed."""
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    total = 0
    pending = b""
    active_tools = {}
    process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, bufsize=0)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    try:
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if now - started > timeout:
                    raise WorkflowError(f"{label} timed out after {timeout}s; child processes were terminated")
                if per_tool_timeout_sec is not None:
                    for tool_id, (tool_name, tool_started) in active_tools.items():
                        if now - tool_started > per_tool_timeout_sec:
                            raise WorkflowError(f"{label} tool {tool_name} exceeded {per_tool_timeout_sec}s; child processes were terminated")
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > byte_limit:
                        raise WorkflowError(f"{label} exceeded the {byte_limit}-byte stream limit")
                    if key.data == "stdout":
                        out.write(chunk)
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            if line.strip():
                                try:
                                    event = json.loads(line)
                                except (ValueError, UnicodeError):
                                    event = None
                                if isinstance(event, dict):
                                    if event.get("type") == "tool_execution_start":
                                        tool_id = event.get("toolCallId", str(len(active_tools)))
                                        active_tools[tool_id] = (event.get("toolName", "unknown"), time.monotonic())
                                    elif event.get("type") == "tool_execution_end":
                                        active_tools.pop(event.get("toolCallId"), None)
                                    if on_event:
                                        on_event(event)
                    else:
                        err.write(chunk)
                        text = chunk.decode(errors="replace").strip()
                        if text:
                            print(f"[{label}] {text[-500:]}", file=sys.stderr, flush=True)
            if pending.strip():
                try:
                    event = json.loads(pending)
                except (ValueError, UnicodeError):
                    event = None
                if isinstance(event, dict):
                    if event.get("type") == "tool_execution_start":
                        tool_id = event.get("toolCallId", str(len(active_tools)))
                        active_tools[tool_id] = (event.get("toolName", "unknown"), time.monotonic())
                    elif event.get("type") == "tool_execution_end":
                        active_tools.pop(event.get("toolCallId"), None)
                    if on_event:
                        on_event(event)
        code = process.wait()
        return code, stdout_path.read_text(encoding="utf-8", errors="replace")
    finally:
        _kill_process_tree(process)
        selector.close()
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def _check_report(stdout: str, job: dict) -> None:
    try:
        report = load_json_from_text(stdout)
    except (ValueError, TypeError) as exc:
        raise WorkflowError(f"Nono preflight returned invalid JSON: {exc}") from exc
    required = ("whole_process_isolation", "credentials_outside_workers", "read_only_inputs",
                "scoped_writes", "network_policy", "tool_budgets", "check_budgets_verified",
                "model_verified", "tools_verified")
    missing = [key for key in required if report.get(key) is not True]
    if missing:
        raise WorkflowError("Nono preflight did not verify: " + ", ".join(missing))
    requested = job.get("model")
    if requested:
        effective = report.get("effective_model") or {}
        if effective.get("model") != requested["model"] or effective.get("thinking") != requested["thinking"]:
            raise WorkflowError(f"Model/effort mismatch: requested {requested}, got {effective}")


def load_json_from_text(text: str):
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty output")
    # The launcher contract emits one object; reject noisy/mixed output.
    value = json.loads(lines[-1], object_pairs_hook=_unique_pairs)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _make_preflight_workspace(config: dict, temp_root: Path) -> Path:
    # Nono's macOS default grants writes to /tmp. Keep even the synthetic preflight
    # workspace under the project so a read-only mount cannot inherit that grant.
    tree_manifest(ROOT / config["paths"]["paper"])
    workspace = temp_root / "workspace"
    workspace.mkdir(parents=True)
    for relative in ("Paper/Work-In-Progress/main.tex",
                     "Paper/Work-In-Progress/main.pdf",
                     "Paper/Work-In-Progress/LatexInclusion/Local-Introduction.tex",
                     "Paper/Work-In-Progress/LatexInclusion/Local-Definitions.tex"):
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic preflight placeholder")
    skills = workspace / "skills"
    skills.mkdir()
    for name in ("skills-paper_writing.md", "skills-paper_citation.md", "BetterBibTeX-preferences.json"):
        (skills / name).write_text("synthetic preflight placeholder\n", encoding="utf-8")
    scout = workspace / "Agent-Outputs/A-Scout"
    (scout / "papers").mkdir(parents=True)
    shutil.copy2(ROOT / "paper_workflow/scout_retrieval.py", workspace / "scout_retrieval.py")
    index = ROOT / "Agent-Outputs/A-Scout/Read-Papers.json"
    if index.is_file():
        shutil.copyfile(index, scout / "Read-Papers.json")
    else:
        write_json(scout / "Read-Papers.json", {"schema_version": 1, "papers": []})
    preflight_pdf = "Agent-Outputs/A-Scout/papers/preflight-new.pdf"
    (workspace / preflight_pdf).write_bytes(b"%PDF-1.4 synthetic preflight placeholder")
    write_json(workspace / "Agent-Outputs/A-Scout/Overview.json", {
        "schema_version": 1, "status": "ok", "papers": [{"id": "S999",
        "doi": "", "url": "https://example.org/preflight", "download_path": preflight_pdf}]})
    for role in AGENT_ORDER[1:]:
        write_json(workspace / OUTPUT_FILES[role], {"preflight_placeholder": True})
    write_json(workspace / CORRECTER_PRIOR_FEEDBACK,
               {"schema_version": 1, "status": "none", "feedback": []})
    baseline = workspace / "source-writer-files"
    for relative in WRITER_FILES:
        target = baseline / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("% synthetic baseline placeholder\n", encoding="utf-8")
    return workspace


def preflight(config: dict, *, run_dir: Path | None = None, announce=True) -> dict:
    """No agent calls: verify every role's Nono profile, exact model, and effort."""
    launcher_argv, runtime = _runtime_args(config)
    if run_dir is None:
        staging_root = ROOT / config["paths"]["outputs"] / "runs"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".preflight-", dir=staging_root) as stage:
            job_root = _make_preflight_workspace(config, Path(stage))
            return _preflight_roles(config, job_root, launcher_argv, runtime, announce)
    return _preflight_roles(config, run_dir, launcher_argv, runtime, announce)


def _preflight_roles(config: dict, run_dir: Path, launcher_argv: list[str], runtime: dict,
                     announce: bool) -> dict:
    report = {}
    paper_hash = manifest_hash(tree_manifest(run_dir / "Paper"))
    for role in (*AGENT_ORDER, *STANDALONE_ROLES):
        rounds = (1, 2) if role == "A-Scout" else (1,)
        for round_number in rounds:
            label = role if round_number == 1 else f"{role}-revision"
            if announce:
                print(f"[preflight] checking {label} sandbox/model", flush=True)
            job = _agent_job(config, "preflight", run_dir, role, round_number,
                             paper_hash, preflight=True)
            jobs = run_dir / "jobs"
            jobs.mkdir(parents=True, exist_ok=True)
            path = jobs / f"{label}.preflight.json"
            write_json(path, job, compact=True)
            out, err = jobs / f"{label}.check.stdout", jobs / f"{label}.check.stderr"
            code, stdout = _run_bounded([*launcher_argv, "check", str(path)], cwd=run_dir,
                                       timeout=config["limits"]["preflight_timeout_sec"],
                                       byte_limit=512_000, stdout_path=out, stderr_path=err,
                                       label=f"preflight {label}")
            if code != 0:
                raise WorkflowError(f"{label} preflight failed (exit {code}); see {err}. No agents were started.")
            _check_report(stdout, job)
            report[label] = {"model": job["model"], "verified": True}
    return {"roles": report, "runtime": {"nono": str(runtime["nono"]), "pi_cli": str(runtime["pi_cli"])}}


def _seed_previous_scout(outputs: Path, run_dir: Path, current_paper_hash: str, max_papers: int) -> bool:
    """Reuse the last complete Scout download set when it matches the same paper snapshot."""
    overview_path = outputs / "A-Scout/Overview.json"
    if not overview_path.is_file():
        return False
    try:
        overview = load_json(overview_path)
        sources = overview.get("papers")
        if (overview.get("schema_version") != 1 or overview.get("status") != "ok"
                or overview.get("paper_sha256") != current_paper_hash
                or not isinstance(sources, list) or len(sources) != max_papers):
            return False
        copies = []
        for paper in sources:
            relative = paper.get("download_path")
            if not isinstance(relative, str) or not relative.startswith("Agent-Outputs/A-Scout/papers/"):
                return False
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                return False
            source = ROOT / path
            if (source.is_symlink() or not source.is_file()
                    or not source.read_bytes().startswith(b"%PDF-")
                    or sha256_file(source) != paper.get("sha256")):
                return False
            copies.append((source, run_dir / path))
        for source, target in copies:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        write_json(run_dir / "Agent-Outputs/A-Scout/Overview.json", overview)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def create_run(config: dict, run_id: str, outputs: Path) -> tuple[Path, dict[str, str]]:
    run_id = _safe_id(run_id)
    run_dir = outputs / "runs" / run_id
    if run_dir.exists():
        raise WorkflowError(f"Run already exists: {run_dir}")
    paper = ROOT / config["paths"]["paper"]
    before = tree_manifest(paper)
    run_dir.mkdir(parents=True)
    shutil.copytree(paper, run_dir / "Paper", ignore=shutil.ignore_patterns(
        ".DS_Store", ".venv", "__pycache__", "*.aux", "*.log", "*.fls", "*.fdb_latexmk",
        "*.blg", "*.bbl", "*.out", "*.toc", "*.dvi", "*.synctex.gz"))
    shutil.copytree(ROOT / "skills", run_dir / "skills", ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
    shutil.copy2(ROOT / "paper_workflow/scout_retrieval.py", run_dir / "scout_retrieval.py")
    scout = run_dir / "Agent-Outputs/A-Scout"
    (scout / "papers").mkdir(parents=True)
    persistent_index = outputs / "A-Scout/Read-Papers.json"
    if persistent_index.is_file():
        shutil.copyfile(persistent_index, scout / "Read-Papers.json")
    else:
        write_json(scout / "Read-Papers.json", {"schema_version": 1, "papers": []})
    seeded = _seed_previous_scout(outputs, run_dir, manifest_hash(before), config["limits"]["max_papers"])
    if not seeded:
        (scout / "Overview.json").unlink(missing_ok=True)
    for role in ("A-Researcher", "A-Writer", "A-Correcter"):
        if role == "A-Correcter":
            prior_path = run_dir / CORRECTER_PRIOR_FEEDBACK
            published = outputs / Path(OUTPUT_FILES["A-Correcter"]).relative_to("Agent-Outputs")
            if published.is_file() and published.stat().st_size <= config["limits"]["max_artifact_bytes"]:
                feedback = load_json(published)
                if feedback.get("schema_version") == 1 and feedback.get("status") in {"ok", "unavailable"}:
                    write_json(prior_path, feedback)
                    continue
            write_json(prior_path, {"schema_version": 1, "status": "none", "feedback": []})
        else:
            write_json(run_dir / OUTPUT_FILES[role], {"preflight_placeholder": True})
    shutil.copy2(run_dir / "Paper/Work-In-Progress/main.tex", run_dir / "source-main.tex")
    baseline_files = run_dir / "source-writer-files"
    for relative in config["writer_files"]:
        target = baseline_files / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run_dir / "Paper" / relative, target)
    for folder in ("jobs", "logs", "build"):
        (run_dir / folder).mkdir(parents=True, exist_ok=True)
    return run_dir, before


def _publish_outputs(project_outputs: Path, run_dir: Path, role: str, payload: dict) -> None:
    relative = Path(OUTPUT_FILES[role]).relative_to("Agent-Outputs")
    destination = project_outputs / relative
    source = run_dir / OUTPUT_FILES[role]
    write_json(source, payload)
    write_json(destination, payload)
    if role == "A-Scout":
        target_papers = project_outputs / "A-Scout/papers"
        target_papers.mkdir(parents=True, exist_ok=True)
        for paper in payload["papers"]:
            local = paper.get("download_path")
            if local:
                relative = Path(local)
                source_file = run_dir / relative
                target_file = project_outputs / relative.relative_to("Agent-Outputs")
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target_file)
    if role == "A-Researcher":
        index = run_dir / "Agent-Outputs/A-Scout/Read-Papers.json"
        if index.is_file():
            shutil.copy2(index, project_outputs / "A-Scout/Read-Papers.json")


def validate_researcher_pdf_reads(researcher: dict, run_dir: Path, observed_read_paths: set[str]) -> None:
    scout = _all_scout_sources(run_dir)
    registry = load_json(run_dir / "Agent-Outputs/A-Scout/Read-Papers.json")
    indexed_ids = {item.get("id") for item in registry.get("papers", []) if isinstance(item, dict)}
    newly_read = {item.get("id") for item in researcher.get("papers_read", []) if isinstance(item, dict)}
    required = {paper.get("download_path") for paper in scout.get("papers", [])
                if paper.get("download_path") and paper.get("id") not in indexed_ids
                and paper.get("id") in newly_read}
    normalized = {Path(path).as_posix().removeprefix("./") for path in observed_read_paths}
    missing = [path for path in required
               if not any(candidate == path or candidate.endswith("/" + path) for candidate in normalized)]
    if missing:
        raise WorkflowError("Researcher marked PDFs as read without successful PDF text extraction/read calls: " + ", ".join(sorted(missing)))


def _ghostscript_source_paths(command: str, source_paths: list[str]) -> list[str]:
    """Return declared PDFs explicitly passed to Ghostscript's text extractor."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    if "gs" not in {Path(token).name for token in tokens} or not any(
            token == "-sDEVICE=txtwrite" or token.startswith("-sDEVICE=txtwrite:") for token in tokens):
        return []
    referenced = [path for path in source_paths if path in tokens]
    if not referenced and "Agent-Outputs/A-Scout/papers/*.pdf" in command:
        referenced = list(source_paths)
    return referenced


def _valid_pdf_text_output(output: str) -> bool:
    lowered = output.lower()
    return len(output) >= 100 and "command not found" not in lowered and "error:" not in lowered


def _provider_error_detail(message: dict) -> str:
    raw = message.get("errorMessage") or message.get("error")
    if isinstance(raw, dict):
        try:
            raw = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            raw = str(raw)
    if not isinstance(raw, str):
        raw = ""
    detail = raw.strip()
    if detail:
        return detail
    content = message.get("content")
    if isinstance(content, list):
        text = "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict) and isinstance(part.get("text"), str)).strip()
        return text
    return ""


def _is_budget_exceeded_error(detail: str) -> bool:
    lowered = detail.lower()
    return ("budget_exceeded" in lowered
            or "monthly budget" in lowered
            or "quota exceeded" in lowered
            or ("http 402" in lowered and "budget" in lowered))


def invoke_agent(config: dict, run_dir: Path, job: dict, prompt: str,
                 launcher_argv: list[str], metrics: dict,
                 progress: Callable[[str, dict], None], log_suffix: str = "") -> dict:
    role = job["agent"]
    round_number = job["round"]
    job_path = run_dir / "jobs" / f"{role}-r{round_number}.json"
    prompt_path = run_dir / "jobs" / f"{role}-r{round_number}.md"
    write_json(job_path, job, compact=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    last_message = None
    settled = False
    tool_count = 0
    read_call_paths = {}
    bash_pdf_call_paths = {}
    observed_read_paths = set()
    scout_pdf_paths = []
    if role == "A-Researcher":
        scout_data = load_json(run_dir / "Agent-Outputs/A-Scout/Overview.json")
        declared_reads = job["permissions"]["read_only"]
        has_scout_directory = "Agent-Outputs/A-Scout" in declared_reads
        scout_pdf_paths = [paper["download_path"] for paper in scout_data.get("papers", [])
                           if paper.get("download_path") and (has_scout_directory
                              or paper["download_path"] in declared_reads)]
    call_output_tokens = 0
    call_cost = 0.0
    cost_complete = True
    agent_label = f"{role} r{round_number}"

    def observe(event):
        nonlocal last_message, settled, tool_count, call_output_tokens, call_cost, cost_complete
        event_type = event.get("type")
        if event_type == "agent_start":
            settled = False
        elif event_type == "agent_settled":
            settled = True
        elif event_type == "tool_execution_start":
            tool_count += 1
            metrics["tool_calls"] += 1
            args = event.get("args") or {}
            if event.get("toolName") == "read" and isinstance(args.get("path"), str):
                read_call_paths[event.get("toolCallId")] = args["path"]
            elif event.get("toolName") == "bash" and isinstance(args.get("command"), str):
                command = args["command"]
                referenced = _ghostscript_source_paths(command, scout_pdf_paths)
                if referenced:
                    bash_pdf_call_paths[event.get("toolCallId")] = referenced
            progress("tool", {"tool": event.get("toolName", "unknown"), "count": tool_count})
        elif event_type == "message_end":
            message = event.get("message", {})
            if message.get("role") == "toolResult":
                tool_id = message.get("toolCallId")
                path = read_call_paths.pop(tool_id, None)
                if path and message.get("toolName") == "read" and not message.get("isError"):
                    extracted = "".join(part.get("text", "") for part in message.get("content", []) if isinstance(part, dict))
                    # Pi's generic reader returns raw PDF bytes; only text/other files count as a read.
                    if Path(path).suffix.lower() != ".pdf" or not extracted.lstrip().startswith("%PDF-"):
                        observed_read_paths.add(Path(path).as_posix().removeprefix("./"))
                bash_paths = bash_pdf_call_paths.pop(tool_id, [])
                if bash_paths and message.get("toolName") == "bash" and not message.get("isError"):
                    output = "".join(part.get("text", "") for part in message.get("content", []) if isinstance(part, dict))
                    if _valid_pdf_text_output(output):
                        observed_read_paths.update(bash_paths)
                return
            if message.get("role") != "assistant":
                return
            last_message = message
            usage = message.get("usage") or {}
            try:
                input_tokens = int(usage.get("input", 0)) + int(usage.get("cacheRead", 0))
                output_tokens = int(usage.get("output", 0))
                total_tokens = int(usage.get("totalTokens", input_tokens + output_tokens))
                cost = (usage.get("cost") or {}).get("total")
                if min(input_tokens, output_tokens, total_tokens) < 0 or not isinstance(cost, (int, float)) or cost < 0:
                    raise ValueError
            except (TypeError, ValueError):
                cost_complete = False
                metrics["cost_complete"] = False
                raise WorkflowError(f"{agent_label} returned incomplete provider usage; stopping to avoid untracked spend")
            call_output_tokens += output_tokens
            call_cost += float(cost)
            metrics["input_tokens"] += input_tokens
            metrics["output_tokens"] += output_tokens
            metrics["total_tokens"] += total_tokens
            metrics["provider_cost_usd"] += float(cost)
            if metrics["input_tokens"] > config["limits"]["max_total_input_tokens"]:
                raise WorkflowError("Run exceeded max_total_input_tokens")
            if metrics["output_tokens"] > config["limits"]["max_total_output_tokens"]:
                raise WorkflowError("Run exceeded max_total_output_tokens")
            if metrics["provider_cost_usd"] > config["limits"]["max_cost_usd"]:
                raise WorkflowError("Run exceeded the configured provider-reported cost cap")
        elif event_type == "auto_retry_start":
            progress("retry", {"reason": event.get("reason", "provider retry")})

    progress("running", {"model": job["model"], "round": round_number})
    stdout_path = run_dir / "logs" / f"{role}-r{round_number}{log_suffix}.jsonl"
    stderr_path = run_dir / "logs" / f"{role}-r{round_number}{log_suffix}.stderr.log"
    try:
        code, _ = _run_bounded([*launcher_argv, "run", str(job_path), str(prompt_path)],
                               cwd=run_dir, timeout=config["limits"]["stage_timeout_sec"],
                               byte_limit=job["limits"]["max_stream_bytes"],
                               stdout_path=stdout_path, stderr_path=stderr_path,
                               on_event=observe, per_tool_timeout_sec=job["limits"]["per_tool_timeout_sec"],
                               label=agent_label)
    except BaseException:
        metrics["cost_complete"] = False
        raise
    if code:
        metrics["cost_complete"] = False
        raise WorkflowError(f"{agent_label} exited with status {code}; see {stderr_path}")
    if not settled:
        metrics["cost_complete"] = False
        raise WorkflowError(f"{agent_label} ended without agent_settled; intermediate output is rejected")
    if not last_message:
        metrics["cost_complete"] = False
        raise WorkflowError(f"{agent_label} returned no completed assistant message")
    if last_message.get("stopReason") != "stop":
        metrics["cost_complete"] = False
        stop_reason = last_message.get("stopReason")
        detail = _provider_error_detail(last_message)
        if stop_reason == "error" and detail and _is_budget_exceeded_error(detail):
            raise WorkflowError(
                f"{agent_label} provider budget exceeded ({detail}). "
                "Increase/reset the provider budget or switch EXAMPLE_PROVIDER_API_KEY credentials, then rerun."
            )
        if detail:
            raise WorkflowError(f"{agent_label} stopped with {stop_reason}: {detail}; see {stderr_path}")
        raise WorkflowError(f"{agent_label} stopped with {stop_reason}; see {stderr_path}")
    content = last_message.get("content", [])
    text = "\n".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    if not text.strip() or len(text.encode("utf-8")) > config["limits"]["max_artifact_bytes"]:
        raise WorkflowError(f"{agent_label} returned empty or oversized JSON")
    try:
        payload = _loads_model_json(text)
    except ValueError as exc:
        raise WorkflowError(f"{agent_label} did not return one valid JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkflowError(f"{agent_label} output must be one JSON object")
    validate_envelope(payload, job)
    validate_agent_payload(role, payload, run_dir, config)
    if role == "A-Researcher":
        validate_researcher_pdf_reads(payload, run_dir, observed_read_paths)
    metrics["last_stage_cost_usd"] = call_cost
    metrics["cost_complete"] = metrics["cost_complete"] and cost_complete
    progress("finished", {"output_tokens": call_output_tokens, "cost_usd": round(call_cost, 6)})
    return payload


def validate_envelope(payload: dict, job: dict) -> None:
    keys = ("schema_version", "run_id", "agent", "round", "paper_sha256", "input_hashes")
    # Researcher status describes handoff completeness, not scientific quality.
    # Normalize legacy partial labels on a complete response; this is not an approval gate.
    if job["agent"] == "A-Researcher" and payload.get("status") == "partial":
        payload["status"] = "ok"
    # Provenance belongs to the controller, not the LLM. Strip any legacy/nested
    # copies and stamp the exact invocation metadata onto the persisted handoff.
    payload.pop("envelope", None)
    for key in keys:
        payload.pop(key, None)
        payload[key] = job[key]
    valid_statuses = {"ok", "partial"} if job["agent"] == "A-Scout" else {"ok"}
    if payload.get("schema_version") != 1 or payload.get("status") not in valid_statuses:
        raise WorkflowError(f"{job['agent']} handoff must use schema_version 1 and status in {sorted(valid_statuses)}")
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        raise WorkflowError("Handoff requires a concise nonempty summary")


def _loads_model_json(raw: str):
    """Parse one JSON response, repairing unescaped LaTeX backslashes safely."""
    repaired = []
    in_string = False
    i = 0
    while i < len(raw):
        char = raw[i]
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            i += 1
            continue
        if char == '"':
            repaired.append(char)
            in_string = False
            i += 1
            continue
        if char != "\\":
            repaired.append(char)
            i += 1
            continue
        if i + 1 >= len(raw):
            repaired.append("\\\\")
            i += 1
            continue
        nxt = raw[i + 1]
        after = raw[i + 2] if i + 2 < len(raw) else ""
        if nxt in '"\\/':
            repaired.extend(("\\", nxt))
            i += 2
        elif nxt == "u" and len(raw[i + 2:i + 6]) == 4 and all(c in "0123456789abcdefABCDEF" for c in raw[i + 2:i + 6]):
            repaired.append(raw[i:i + 6])
            i += 6
        elif nxt in "bfnrt" and after and after.isalpha():
            # In scholarly JSON, \text, \frac, \rho, \begin, etc. are LaTeX
            # commands, not JSON control escapes. Strings are required single-line.
            repaired.extend(("\\\\", nxt))
            i += 2
        elif nxt in "bfnrt":
            repaired.extend(("\\", nxt))
            i += 2
        else:
            # JSON forbids these escape sequences; treat the slash literally.
            repaired.extend(("\\\\", nxt))
            i += 2
    value = json.loads("".join(repaired), object_pairs_hook=_unique_pairs)
    def check_strings(item):
        # Escaped line breaks/tabs are valid JSON and useful in proof/patch fields;
        # reject only non-whitespace C0 controls after decoding.
        if isinstance(item, str) and any(ord(ch) < 32 and ch not in "\n\r\t" for ch in item):
            raise ValueError("JSON string contains an unsupported control character")
        if isinstance(item, dict):
            for child in item.values():
                check_strings(child)
        elif isinstance(item, list):
            for child in item:
                check_strings(child)
    check_strings(value)
    return value


def _require_text(value, label, maximum=12000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise WorkflowError(f"{label} must be nonempty and <= {maximum} UTF-8 bytes")
    return value


def _canonicalize_research_sources(payload: dict, run_dir: Path) -> tuple[set[str], set[str], set[str]]:
    if not isinstance(payload.get("papers_read"), list) or not isinstance(payload.get("prior_papers_reused"), list):
        raise WorkflowError("Research handoff must report new and previously read papers separately")
    registry = load_json(run_dir / "Agent-Outputs/A-Scout/Read-Papers.json")
    indexed_ids = {item.get("id") for item in registry.get("papers", []) if isinstance(item, dict)}
    prior_ids = list(payload["prior_papers_reused"])
    if any(not isinstance(source_id, str) or not source_id for source_id in prior_ids):
        raise WorkflowError("prior_papers_reused must contain string IDs")
    current_reads = []
    for record in payload["papers_read"]:
        if isinstance(record, dict) and record.get("id") in indexed_ids:
            prior_ids.append(record["id"])
        else:
            current_reads.append(record)
    prior_ids = list(dict.fromkeys(prior_ids))
    payload["papers_read"] = current_reads
    payload["prior_papers_reused"] = prior_ids
    new_ids = [item.get("id") for item in current_reads if isinstance(item, dict)]
    if len(new_ids) != len(current_reads) or len(new_ids) != len(set(new_ids)):
        raise WorkflowError("papers_read must contain unique source-ID records")
    if len(prior_ids) != len(set(prior_ids)):
        raise WorkflowError("prior_papers_reused must contain unique IDs")
    unknown_prior_ids = sorted(set(prior_ids) - indexed_ids)
    if unknown_prior_ids:
        raise WorkflowError("prior_papers_reused must contain unique IDs already in Read-Papers.json; unknown IDs: "
                            + ", ".join(unknown_prior_ids))
    if set(new_ids) & set(prior_ids):
        raise WorkflowError("A source cannot be both newly read and previously read")
    scout = _all_scout_sources(run_dir)
    scout_ids = {paper["id"] for paper in scout.get("papers", [])}
    if set(new_ids) - scout_ids or set(new_ids) & indexed_ids:
        raise WorkflowError("papers_read must reference current Scout sources not already in the read index")
    return scout_ids, set(new_ids), set(prior_ids)


def validate_agent_payload(role: str, payload: dict, run_dir: Path, config: dict) -> None:
    limits = config["limits"]
    if role == "A-Scout":
        papers = payload.get("papers")
        techniques = payload.get("techniques")
        queries = payload.get("queries")
        if not isinstance(papers, list):
            raise WorkflowError("A-Scout papers must be a list")
        papers, discarded_identity_records = scout_retrieval.deduplicate_records(papers, limits["max_papers"])
        if discarded_identity_records:
            payload["discarded_duplicate_records"] = [item.get("id") for item in discarded_identity_records
                                                       if isinstance(item, dict)]
            payload["papers"] = papers
        if len(papers) > limits["max_papers"]:
            # Keep the controller's hard maximum deterministic. The prompt asks the
            # model not to exceed it, but malformed over-complete responses are
            # safely truncated before downstream validation; the discarded IDs are
            # recorded for auditability.
            payload["discarded_excess_sources"] = [
                item.get("id") if isinstance(item, dict) else None
                for item in papers[limits["max_papers"]:]
            ]
            papers = papers[:limits["max_papers"]]
            payload["papers"] = papers
        if not papers and payload.get("status") != "partial":
            raise WorkflowError("A-Scout status=ok requires verified source records; use status=partial and state the blocker")
        if not isinstance(techniques, list) or not isinstance(queries, list):
            raise WorkflowError("A-Scout requires techniques and queries arrays")
        seen = set()
        total_bytes = 0
        index_path = run_dir / "Agent-Outputs/A-Scout/Read-Papers.json"
        prior_index = load_json(index_path) if index_path.is_file() else {"schema_version": 1, "papers": []}
        prior_papers = prior_index.get("papers")
        if prior_index.get("schema_version") != 1 or not isinstance(prior_papers, list):
            raise WorkflowError("A-Scout Read-Papers.json has an unsupported/corrupt schema")
        prior_ids = [item.get("id") for item in prior_papers if isinstance(item, dict)]
        if len(prior_ids) != len(prior_papers) or any(not isinstance(value, str) or not value for value in prior_ids) or len(set(prior_ids)) != len(prior_ids):
            raise WorkflowError("A-Scout Read-Papers.json contains missing/duplicate paper IDs")
        known = {_source_fingerprint(item): item for item in prior_papers if _source_fingerprint(item)}
        prior_by_id = {item["id"]: item for item in prior_papers}
        previous_overview_path = run_dir / OUTPUT_FILES["A-Scout"]
        try:
            previous_overview = load_json(previous_overview_path) if previous_overview_path.is_file() else {}
        except (OSError, ValueError):
            previous_overview = {}
        previous_papers = previous_overview.get("papers", [])
        previous_by_id = {item.get("id"): item for item in previous_papers if isinstance(item, dict)}
        previous_by_fingerprint = {_source_fingerprint(item): item for item in previous_papers
                                   if isinstance(item, dict) and _source_fingerprint(item)}
        partial = payload.get("status") == "partial"
        id_normalizations = []
        for paper in papers:
            _require_text(paper.get("id"), "A-Scout paper.id", 200)
            _require_text(paper.get("title"), "A-Scout paper.title", 1000)
            if isinstance(paper.get("authors"), list) and all(isinstance(author, str) and author.strip() for author in paper["authors"]):
                paper["authors"] = ", ".join(author.strip() for author in paper["authors"])
            indexed_record = prior_by_id.get(paper["id"])
            if paper.get("retrieved_at") in (None, "") and isinstance(indexed_record, dict):
                # Persistent read records call this timestamp `read_at`; promote it
                # when a Scout omits the synonymous timestamp on a reused source.
                indexed_read_at = indexed_record.get("read_at")
                if isinstance(indexed_read_at, str) and indexed_read_at.strip():
                    paper["retrieved_at"] = indexed_read_at
                elif not partial:
                    # The controller has revalidated this selected record in the
                    # current run; use today's date rather than dropping it for a
                    # missing legacy timestamp.
                    paper["retrieved_at"] = utc_now().split("T", 1)[0]
            metadata_fields = ("authors", "url", "locator", "support", "relevance", "transfer_limits", "retrieved_at")
            for key in metadata_fields:
                value = paper.get(key)
                if not partial or value not in (None, ""):
                    _require_text(value, f"A-Scout paper.{key}", 5000)
            if isinstance(paper.get("year"), int) and not isinstance(paper.get("year"), bool):
                paper["year"] = str(paper["year"])
            if not partial or paper.get("year") not in (None, ""):
                _require_text(paper.get("year"), "A-Scout paper.year", 200)
            if paper.get("url"):
                if not isinstance(paper["url"], str) or not paper["url"].startswith(("https://", "http://")):
                    if partial:
                        paper["url"] = ""
                    else:
                        raise WorkflowError("A-Scout source URLs must be HTTP(S)")
            fingerprint = _source_fingerprint(paper)
            if paper["id"] in seen:
                # Duplicate source IDs are harmless for discovery: retain the
                # first record and ignore later repetitions, rather than failing
                # the entire Scout handoff. The discarded ID remains auditable.
                payload.setdefault("discarded_duplicate_source_ids", []).append(paper["id"])
                continue
            seen.add(paper["id"])
            prior_with_id = prior_by_id.get(paper["id"])
            if prior_with_id and fingerprint and _source_fingerprint(prior_with_id) != fingerprint:
                reported_id = paper["id"]
                reserved = set(prior_ids) | {item.get("id") for item in papers if isinstance(item, dict)} | seen
                numbers = [int(match.group(1)) for value in reserved
                           if isinstance(value, str) and (match := re.fullmatch(r"S(\d+)", value))]
                next_number = max(numbers, default=0) + 1
                assigned_id = f"S{next_number}"
                while assigned_id in reserved:
                    next_number += 1
                    assigned_id = f"S{next_number}"
                paper["id"] = assigned_id
                seen.remove(reported_id)
                seen.add(assigned_id)
                id_normalizations.append({"reported_id": reported_id, "assigned_id": assigned_id,
                                          "reason": "reported ID was already bound to a different DOI/URL in Read-Papers.json"})
            prior = known.get(fingerprint) if fingerprint else None
            if prior and paper["id"] != prior.get("id"):
                reported_id = paper["id"]
                stable_id = prior.get("id")
                if stable_id in seen:
                    raise WorkflowError("A-Scout reported duplicate records for a previously indexed source")
                seen.remove(reported_id)
                paper["id"] = stable_id
                seen.add(stable_id)
                id_normalizations.append({"reported_id": reported_id, "assigned_id": stable_id,
                                          "reason": "stable DOI/URL matched an indexed source; controller restored its persistent ID"})
            download = paper.get("download_path")
            if not download and not partial:
                previous = previous_by_id.get(paper["id"]) or previous_by_fingerprint.get(fingerprint)
                previous_path = previous.get("download_path") if isinstance(previous, dict) else None
                if isinstance(previous_path, str) and previous.get("sha256"):
                    relative_previous = Path(previous_path)
                    candidate_path = run_dir / relative_previous
                    if (not relative_previous.is_absolute() and ".." not in relative_previous.parts
                            and previous_path.startswith("Agent-Outputs/A-Scout/papers/")
                            and candidate_path.is_file() and not candidate_path.is_symlink()
                            and candidate_path.read_bytes().startswith(b"%PDF-")
                            and sha256_file(candidate_path) == previous["sha256"]):
                        download = previous_path
                        paper["download_path"] = previous_path
                        payload.setdefault("reused_previous_pdf_paths", []).append(previous_path)
            if not download and isinstance(paper.get("doi"), str) and paper.get("doi"):
                # A-Scout may select an indexed DOI and invoke the deterministic
                # downloader but forget to echo its returned stable path. Rebind
                # only the exact DOI-derived filename after title verification.
                recovered = f"Agent-Outputs/A-Scout/papers/{scout_retrieval.doi_pdf_filename(paper['doi'])}"
                recovered_path = run_dir / recovered
                if recovered_path.is_file() and not recovered_path.is_symlink():
                    verified = scout_retrieval.verify_pdf_text(recovered_path, paper.get("title", ""))
                    if verified.get("ok"):
                        download = recovered
                        paper["download_path"] = recovered
                        payload.setdefault("recovered_doi_download_paths", []).append(recovered)
            if download:
                path = Path(download)
                if path.is_absolute() or ".." in path.parts or not download.startswith("Agent-Outputs/A-Scout/papers/"):
                    # Treat a model-reported path in another role's folder as an
                    # invalid candidate record, not as permission to inspect it.
                    misplaced = run_dir / path
                    if misplaced.is_file() and not misplaced.is_symlink():
                        misplaced.unlink()
                    paper["download_path"] = None
                    payload.setdefault("discarded_invalid_download_paths", []).append(download)
                    continue
                target = run_dir / path
                if target.is_symlink() or target.suffix.lower() != ".pdf":
                    raise WorkflowError(f"A-Scout download path is invalid: {download}")
                if not target.is_file():
                    if partial or prior is not None:
                        paper["download_path"] = None
                        payload.setdefault("discarded_missing_download_paths", []).append(download)
                        continue
                    raise WorkflowError(f"A-Scout did not save the declared paper PDF: {download}")
                size = target.stat().st_size
                if size <= 0 or size > limits["max_paper_bytes"] or not target.read_bytes().startswith(b"%PDF-"):
                    if partial or prior is not None:
                        target.unlink(missing_ok=True)
                        paper["download_path"] = None
                        continue
                    raise WorkflowError(f"Downloaded paper is invalid or exceeds {limits['max_paper_bytes']} bytes")
                file_hash = sha256_file(target)
                if prior and prior.get("sha256") and prior["sha256"] != file_hash:
                    # A model may redownload a different version of an already indexed
                    # source under the stable ID. Prefer the trusted indexed record and
                    # discard the conflicting local PDF rather than accepting changed bytes.
                    target.unlink(missing_ok=True)
                    paper["download_path"] = None
                    paper["sha256"] = prior["sha256"]
                    paper["bytes"] = 0
                    payload.setdefault("discarded_changed_indexed_pdfs", []).append(paper["id"])
                    continue
                total_bytes += size
                paper["sha256"] = file_hash
                paper["bytes"] = size
        if total_bytes > limits["max_total_download_bytes"]:
            raise WorkflowError("A-Scout downloads exceed the run's total PDF budget")
        papers_dir = run_dir / "Agent-Outputs/A-Scout/papers"
        declared_downloads = {paper["download_path"] for paper in papers if paper.get("download_path")}
        actual_downloads = {path.relative_to(run_dir).as_posix() for path in papers_dir.rglob("*")
                            if path.is_file() and ".cache" not in path.parts}
        discarded_undeclared = sorted(actual_downloads - declared_downloads)
        if discarded_undeclared:
            payload["discarded_undeclared_files"] = discarded_undeclared
            previous_path = run_dir / "Agent-Outputs/A-Scout/Overview.json"
            try:
                previous = load_json(previous_path)
            except (OSError, ValueError):
                previous = {}
            prior_hashes = {item.get("download_path"): item.get("sha256")
                            for item in previous.get("papers", []) if isinstance(item, dict) and item.get("download_path")}
            # A Scout may intentionally drop a cached PDF after finding that it does
            # not match its metadata. Remove only byte-identical files from the previous
            # trusted Overview; never silently drop a new/unreported file.
            for rel in discarded_undeclared:
                stale = run_dir / rel
                if stale.is_file():
                    stale.unlink()
        actual_downloads = {path.relative_to(run_dir).as_posix() for path in papers_dir.rglob("*")
                            if path.is_file() and ".cache" not in path.parts}
        if actual_downloads != declared_downloads:
            raise WorkflowError("A-Scout papers folder contains undeclared files or an unreported download")
        id_aliases = {item["reported_id"]: item["assigned_id"] for item in id_normalizations}
        valid_techniques = []
        for technique_index, technique in enumerate(techniques, start=1):
            if not isinstance(technique, dict):
                raise WorkflowError("A-Scout techniques must contain objects")
            if not isinstance(technique.get("id"), str) or not technique.get("id").strip():
                technique["id"] = f"T{technique_index}"
                payload.setdefault("normalized_technique_ids", []).append(technique["id"])
            if technique.get("paper_id") in id_aliases:
                technique["paper_id"] = id_aliases[technique["paper_id"]]
            required_technique_keys = ("id", "paper_id", "bottleneck", "method", "success_conditions", "first_test")
            missing_technique = [key for key in required_technique_keys
                                 if not isinstance(technique.get(key), str) or not technique.get(key).strip()]
            if missing_technique:
                payload.setdefault("discarded_incomplete_techniques", []).append({
                    "id": technique.get("id"), "missing": missing_technique})
                continue
            for key in required_technique_keys:
                _require_text(technique.get(key), f"A-Scout technique.{key}", 5000)
            if technique["paper_id"] not in seen:
                payload.setdefault("discarded_unknown_techniques", []).append(technique.get("id"))
                continue
            valid_techniques.append(technique)
        payload["techniques"] = valid_techniques
        if id_normalizations:
            payload["id_normalizations"] = id_normalizations
        for query_index, query in enumerate(queries, start=1):
            if not isinstance(query, dict):
                raise WorkflowError(f"A-Scout queries[{query_index}] must be an object")
            _require_text(query.get("query"), f"A-Scout queries[{query_index}].query")
            if "outcome" not in query and isinstance(query.get("result"), str):
                # Older Scout responses used `result`; persist the canonical key so
                # downstream consumers see one stable handoff schema.
                query["outcome"] = query.pop("result")
            if "outcome" not in query:
                raise WorkflowError(
                    f"A-Scout queries[{query_index}].outcome is missing; provide nonempty UTF-8 text"
                )
            _require_text(query["outcome"], f"A-Scout queries[{query_index}].outcome", 12000)
        if isinstance(payload.get("limitations"), list) and all(isinstance(item, str) for item in payload["limitations"]):
            payload["limitations"] = "; ".join(item.strip() for item in payload["limitations"] if item.strip())
        _require_text(payload.get("limitations"), "A-Scout limitations", 5000)
    elif role == "A-Researcher":
        ideas = payload.get("ideas")
        if not isinstance(ideas, list) or len(ideas) > limits["max_ideas"]:
            raise WorkflowError("A-Researcher ideas must be a list within the configured handoff limit")
        ids = set()
        for idea in ideas:
            if not isinstance(idea, dict):
                raise WorkflowError("A-Researcher ideas must contain objects")
            if isinstance(idea.get("source_context"), dict):
                idea["source_context"] = " | ".join(
                    f"{key}: {value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}"
                    for key, value in idea["source_context"].items())
            impact_map = idea.get("impact_map")
            if not isinstance(impact_map, list) or not impact_map:
                raise WorkflowError("A-Researcher ideas require a nonempty manuscript impact_map")
            impact_ids = set()
            allowed_paper_paths = {"Paper/" + item for item in WRITER_FILES}
            valid_impact_map = []
            for item in impact_map:
                if not isinstance(item, dict):
                    raise WorkflowError("Researcher impact_map entries must be objects")
                for key in ("id", "file", "locator", "linked_claim", "required_edit"):
                    _require_text(item.get(key), f"A-Researcher impact_map.{key}", limits["max_artifact_bytes"])
                if item["file"] not in allowed_paper_paths:
                    raise WorkflowError("Researcher impact_map files must be Writer-allowed")
                if item["id"] in impact_ids:
                    idea.setdefault("discarded_duplicate_impact_ids", []).append(item["id"])
                    continue
                impact_ids.add(item["id"])
                valid_impact_map.append(item)
            idea["impact_map"] = valid_impact_map
            for key in ("id", "title", "kind", "target", "source_context", "bottleneck", "statement",
                        "narrative_role"):
                _require_text(idea.get(key), f"A-Researcher idea.{key}", limits["max_artifact_bytes"])
            for optional_text in ("proof", "falsification_test"):
                value = idea.get(optional_text)
                if value is None:
                    continue
                if optional_text == "falsification_test" and isinstance(value, dict):
                    value = "\n".join(f"{key}: {item}" for key, item in value.items())
                    idea[optional_text] = value
                elif optional_text == "falsification_test" and isinstance(value, list):
                    value = "\n".join(str(item) for item in value)
                    idea[optional_text] = value
                if not isinstance(value, str):
                    value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    idea[optional_text] = value
                if not value.strip():
                    idea[optional_text] = ""
                else:
                    _require_text(value, f"A-Researcher idea.{optional_text}", limits["max_artifact_bytes"])
            kind = str(idea["kind"]).strip().lower()
            kind_aliases = {"correctness repair": "correction", "proof repair": "correction",
                            "repair": "correction", "scope_correction": "correction",
                            "research extension": "extension", "incremental development": "extension",
                            "incremental_result": "extension", "improvement": "extension", "new result": "extension"}
            idea["kind"] = kind_aliases.get(kind, kind)
            if idea["kind"] not in {"correction", "extension"}:
                raise WorkflowError("A-Researcher idea.kind must be correction or extension")
            if idea["id"] in ids:
                raise WorkflowError("A-Researcher idea IDs must be unique")
            ids.add(idea["id"])
            if isinstance(idea.get("prior_work"), str):
                idea["prior_work"] = [idea["prior_work"]]
            elif isinstance(idea.get("prior_work"), list) and any(isinstance(item, dict) for item in idea["prior_work"]):
                converted = []
                for item in idea["prior_work"]:
                    if isinstance(item, dict):
                        source_id = next((item.get(key) for key in ("source_id", "source", "paper_id", "id")
                                          if isinstance(item.get(key), str) and item[key].strip()), None)
                        details = []
                        difference = item.get("difference")
                        if isinstance(source_id, str) and source_id.strip():
                            if isinstance(difference, str) and difference.strip():
                                details.append(f"{source_id.strip()}: {difference.strip()}")
                            else:
                                details.append(source_id.strip())
                        for key in ("title", "locator", "relevance", "summary", "context"):
                            value = item.get(key)
                            if isinstance(value, str) and value.strip():
                                details.append(f"{key}: {value.strip()}")
                        if not details:
                            details.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
                        converted.append("; ".join(details))
                    else:
                        converted.append(item)
                idea["prior_work"] = converted
            if isinstance(idea.get("paper_changes"), list) and any(isinstance(item, dict) for item in idea["paper_changes"]):
                converted = []
                for item in idea["paper_changes"]:
                    if isinstance(item, dict):
                        file_path = item.get("file")
                        locator = item.get("locator")
                        replacement = next((item.get(key) for key in ("replace", "replacement", "replacement_text", "replacement_latex", "new_text", "text", "latex", "change", "action", "new", "old")
                                            if isinstance(item.get(key), str)), None)
                        if not all(isinstance(value, str) and value.strip()
                                   for value in (file_path, locator, replacement)):
                            raise WorkflowError("Researcher paper_changes objects require file, locator, and replacement text")
                        converted.append(f"{file_path} — {locator}:\n{replacement}")
                    else:
                        converted.append(item)
                idea["paper_changes"] = converted
            for key in ("assumptions", "prior_work", "caveats", "paper_changes"):
                if key not in idea:
                    idea[key] = []
                if isinstance(idea.get(key), str):
                    value = idea[key].strip()
                    idea[key] = [value] if value else []
            for key in ("assumptions", "prior_work", "caveats", "paper_changes"):
                if not isinstance(idea.get(key), list) or any(not isinstance(value, str) or not value.strip() for value in idea[key]):
                    raise WorkflowError(f"A-Researcher {key} must be an array of nonempty strings")
        if isinstance(payload.get("narrative_plan"), str) and payload["narrative_plan"].strip():
            payload["narrative_plan"] = [payload["narrative_plan"].strip()]
        if not isinstance(payload.get("narrative_plan"), list) or not payload["narrative_plan"] or any(not isinstance(item, str) or not item.strip() for item in payload["narrative_plan"]):
            raise WorkflowError("A-Researcher requires a concise narrative_plan array of nonempty strings")
        scout_ids, new_ids, prior_ids = _canonicalize_research_sources(payload, run_dir)
        source_refs = set()
        for idea in ideas:
            for item in idea["prior_work"]:
                source_refs.update(re.findall(r"\bS\d+\b", item))
        if source_refs - (set(new_ids) | set(prior_ids)):
            raise WorkflowError("Researcher used Scout source IDs in prior_work without recording them as read or reused")
    elif role == "A-Writer":
        _require_text(payload.get("summary"), "A-Writer summary", 5000)
        if (not isinstance(payload.get("integrated_idea_ids"), list)
                or not isinstance(payload.get("changed_files"), list)
                or len(payload["changed_files"]) != len(set(payload["changed_files"]))):
            raise WorkflowError("A-Writer must report unique integrated IDs and changed files")
        if payload.get("unresolved") != []:
            raise WorkflowError("A-Writer must resolve all Researcher work before completion")
        researcher = load_json(run_dir / OUTPUT_FILES["A-Researcher"])
        expected_ids = [idea.get("id") for idea in researcher.get("ideas", [])]
        if payload["integrated_idea_ids"] != expected_ids:
            raise WorkflowError("A-Writer must report every A-Researcher idea exactly once")
    elif role == "A-Correcter":
        feedback = payload.get("feedback")
        queries = payload.get("queries")
        limitations = payload.get("limitations")
        if not isinstance(feedback, list) or not isinstance(queries, list):
            raise WorkflowError("A-Correcter requires feedback and queries arrays")
        if len(feedback) > 8 or len(queries) > 10:
            raise WorkflowError("A-Correcter feedback exceeds its bounded result count")
        if isinstance(limitations, list) and all(isinstance(item, str) for item in limitations):
            payload["limitations"] = "; ".join(item.strip() for item in limitations if item.strip())
        if not isinstance(payload.get("limitations"), str) or not payload["limitations"].strip():
            payload["limitations"] = "No additional limitations reported."
        _require_text(payload.get("limitations"), "A-Correcter limitations", 5000)
        feedback_ids = set()
        for item in feedback:
            if not isinstance(item, dict):
                raise WorkflowError("A-Correcter feedback entries must be objects")
            for key in ("id", "manuscript_area", "potential_direction"):
                _require_text(item.get(key), f"A-Correcter feedback.{key}", 5000)
            for key in ("existing_result", "follow_up"):
                if not isinstance(item.get(key), str):
                    item[key] = ""
                if item[key].strip():
                    _require_text(item[key], f"A-Correcter feedback.{key}", 5000)
            if item["id"] in feedback_ids:
                raise WorkflowError("A-Correcter feedback IDs must be unique")
            feedback_ids.add(item["id"])
            techniques = item.get("techniques")
            if not isinstance(techniques, list) or len(techniques) > 5:
                raise WorkflowError("A-Correcter techniques must be a list of at most five names")
            for technique in techniques:
                if not isinstance(technique, dict):
                    raise WorkflowError("A-Correcter technique entries must be objects")
                for key in ("name", "source_title"):
                    _require_text(technique.get(key), f"A-Correcter technique.{key}", 3000)
                if isinstance(technique.get("authors"), list):
                    technique["authors"] = "; ".join(str(author) for author in technique["authors"] if str(author).strip())
                if isinstance(technique.get("year"), int) and not isinstance(technique["year"], bool):
                    technique["year"] = str(technique["year"])
                for key in ("authors", "year", "relevance"):
                    if not isinstance(technique.get(key), str):
                        technique[key] = ""
                if not (isinstance(technique.get("doi"), str) and technique["doi"].strip()
                        or isinstance(technique.get("url"), str) and technique["url"].startswith("https://")):
                    raise WorkflowError("A-Correcter techniques require a DOI or HTTPS source URL")
        for query in queries:
            if not isinstance(query, dict):
                raise WorkflowError("A-Correcter query records must be objects")
            _require_text(query.get("query"), "A-Correcter query")
            _require_text(query.get("outcome"), "A-Correcter query outcome", 12000)


def _scout_is_complete(run_dir: Path, scout: dict, config: dict) -> bool:
    """Require five verified records, with local PDFs for all non-indexed sources."""
    papers = scout.get("papers", [])
    maximum = config["limits"]["max_papers"]
    if scout.get("status") != "ok" or len(papers) != maximum:
        return False
    registry = load_json(run_dir / "Agent-Outputs/A-Scout/Read-Papers.json")
    indexed_ids = {item.get("id") for item in registry.get("papers", []) if isinstance(item, dict)}
    return all((paper.get("download_path") and (run_dir / paper["download_path"]).is_file())
               or paper.get("id") in indexed_ids for paper in papers)


def _scout_completion_note(scout: dict, config: dict) -> str:
    missing = max(0, config["limits"]["max_papers"] - len(scout.get("papers", [])))
    no_pdf = sum(not paper.get("download_path") for paper in scout.get("papers", []))
    limitation = str(scout.get("limitations", "no details provided")).strip()
    return (f"Scout status={scout.get('status')}; source records={len(scout.get('papers', []))}/"
            f"{config['limits']['max_papers']}; records without a new PDF={no_pdf}; missing records={missing}. "
            f"Limitations: {limitation}")[:1800]


def _persist_research_index(run_dir: Path, researcher: dict, scout: dict) -> None:
    index_path = run_dir / "Agent-Outputs/A-Scout/Read-Papers.json"
    index = load_json(index_path)
    if index.get("schema_version") != 1 or not isinstance(index.get("papers"), list):
        raise WorkflowError("Read-Papers.json has an unsupported/corrupt schema")
    index_ids = [item.get("id") for item in index["papers"] if isinstance(item, dict)]
    if len(index_ids) != len(index["papers"]) or any(not isinstance(value, str) or not value for value in index_ids) or len(set(index_ids)) != len(index_ids):
        raise WorkflowError("Read-Papers.json contains missing/duplicate paper IDs")
    existing = {item.get("id"): item for item in index["papers"]}
    scout_ids = {item["id"] for item in scout["papers"]}
    reused = researcher["prior_papers_reused"]
    if any(not isinstance(value, str) or not value for value in reused):
        raise WorkflowError("Researcher prior_papers_reused must contain source ID strings")
    newly_read = [item.get("id") for item in researcher["papers_read"]]
    if len(newly_read) != len(set(newly_read)) or set(newly_read) & set(reused):
        raise WorkflowError("Researcher must not mark a paper as both newly read and previously read")
    known_fingerprints = {_source_fingerprint(item): item for item in index["papers"] if _source_fingerprint(item)}
    for source in scout["papers"]:
        fingerprint = _source_fingerprint(source)
        previous = known_fingerprints.get(fingerprint) if fingerprint else None
        if previous and source["id"] != previous.get("id"):
            raise WorkflowError("Scout changed a persistent source ID; keep IDs stable across runs")
    for item in researcher["papers_read"]:
        paper_id = item.get("id")
        if paper_id not in scout_ids:
            raise WorkflowError(f"Researcher claims to have read a source not supplied by Scout: {paper_id}")
        if paper_id in existing:
            raise WorkflowError(f"Researcher attempted to read the same paper twice: {paper_id}")
        _require_text(item.get("summary"), "Read-Papers summary", 4000)
        _require_text(item.get("locator"), "Read-Papers locator", 1000)
        source = next(paper for paper in scout["papers"] if paper["id"] == paper_id)
        existing[paper_id] = {"id": paper_id, "doi": source.get("doi", ""), "url": source["url"],
                              "title": source["title"], "sha256": source.get("sha256", ""),
                              "summary": item["summary"][:350], "locator": item["locator"],
                              "read_at": utc_now()}
    for paper_id in researcher["prior_papers_reused"]:
        if paper_id not in existing:
            raise WorkflowError(f"Researcher reused an unknown prior paper ID: {paper_id}")
    write_json(index_path, {"schema_version": 1, "papers": list(existing.values())}, compact=True)


def execute_pipeline(config: dict, run_id: str, run_dir: Path, outputs: Path,
                     paper_hash: str, agent_call: Callable, build_call: Callable,
                     status_call: Callable, metrics: dict | None = None,
                     research_brief: str = "", researcher_comments: str = "") -> dict:
    """Run the bounded state machine. Inject calls in tests; live callers use Nono/Pi."""
    metrics = metrics if metrics is not None else {
        "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
        "provider_cost_usd": 0.0, "tool_calls": 0, "cost_complete": True}
    def call(role, round_number):
        status_call("running", role, {"round": round_number})
        job = _agent_job(config, run_id, run_dir, role, round_number, paper_hash,
                         research_brief=research_brief, researcher_comments=researcher_comments)
        prompt = _prompt(config, role, job, run_dir)
        if role in {"A-Researcher", "A-Writer"}:
            write_json(run_dir / "jobs" / f"{role}-r{round_number}.json", job, compact=True)
            (run_dir / "jobs" / f"{role}-r{round_number}.md").write_text(prompt, encoding="utf-8")
            _write_stage_checkpoint(run_dir, job, prompt, metrics)
        payload = agent_call(role, round_number, job, prompt, metrics)
        validate_envelope(payload, job)
        validate_agent_payload(role, payload, run_dir, config)
        _write_completion_checkpoint(run_dir, job, prompt, payload, metrics)
        return payload

    scout = None
    scout_retry_limit = config["limits"]["max_scout_retries"]
    for scout_attempt in range(scout_retry_limit + 1):
        scout_round = scout_attempt + 1
        scout = call("A-Scout", scout_round)
        write_json(run_dir / OUTPUT_FILES["A-Scout"], scout)
        if _scout_is_complete(run_dir, scout, config):
            _publish_outputs(outputs, run_dir, "A-Scout", scout)
            status_call("finished", "A-Scout", {"round": scout_round, "paper_count": len(scout["papers"])})
            break
        note = _scout_completion_note(scout, config)
        if scout_attempt >= scout_retry_limit:
            _publish_outputs(outputs, run_dir, "A-Scout", scout)
            status_call("scout_incomplete", "A-Scout", {"attempts": scout_round, "reason": note})
            print(f"[workflow] A-Scout remained incomplete after {scout_round} bounded attempt(s): {note}", file=sys.stderr)
            return {"outcome": "scout_incomplete", "scout": scout, "reason": note, "metrics": metrics}
        status_call("revision", "A-Scout", {"reason": note, "round": scout_round + 1})
        # Keep partial local PDFs available to the repair attempt. Its read/write
        # scope includes only Scout's own papers directory and Overview.json.
    assert scout is not None
    researcher = call("A-Researcher", 1)
    write_json(run_dir / OUTPUT_FILES["A-Researcher"], researcher)
    _persist_research_index(run_dir, researcher, _all_scout_sources(run_dir))
    _publish_outputs(outputs, run_dir, "A-Researcher", researcher)
    status_call("finished", "A-Researcher", {"round": 1, "idea_count": len(researcher["ideas"])})
    writer = call("A-Writer", 1)
    expected_ids = [idea["id"] for idea in researcher["ideas"]]
    if writer["integrated_idea_ids"] != expected_ids:
        raise WorkflowError("Writer must integrate every Researcher idea exactly once")
    writer_manifest = tree_manifest(run_dir / "Paper")
    changed = sorted(path for path in set(_initial_manifest(run_dir).keys()) | set(writer_manifest)
                     if _initial_manifest(run_dir).get(path) != writer_manifest.get(path))
    allowed = set(config["writer_files"])
    if not changed or not set(changed) <= allowed:
        raise WorkflowError("Writer made no manuscript changes or changed files outside its five-file allowlist: " + repr(changed))
    declared = set(writer["changed_files"])
    if declared != set(changed):
        raise WorkflowError(f"Writer changed_files does not match actual diff: declared={sorted(declared)}, actual={changed}")
    validate_manuscript_invariants(run_dir / "Paper", changed)
    write_json(run_dir / OUTPUT_FILES["A-Writer"], writer)
    status_call("finished", "A-Writer", {"changed_files": changed})
    status_call("building", "A-Writer", {"variants": ["normal", "highlight_disabled"]})

    build = build_call(run_dir)
    writer["build"] = build
    write_json(run_dir / OUTPUT_FILES["A-Writer"], writer)
    status_call("built", "A-Writer", build)
    return {"outcome": "completed", "scout": scout, "researcher": researcher,
            "writer": writer, "build": build, "metrics": metrics, "changed_files": changed}


def _run_correcter_feedback(config: dict, run_id: str, run_dir: Path, outputs: Path,
                            paper_hash: str, version: str, metrics: dict,
                            agent_call: Callable, status_call: Callable) -> dict:
    """Run post-Writer feedback; its failure never blocks an already-built version."""
    role = "A-Correcter"
    base = {"schema_version": 1, "run_id": run_id, "agent": role, "round": 1,
            "paper_sha256": paper_hash}
    try:
        job = _agent_job(config, run_id, run_dir, role, 1, paper_hash)
        prompt = _prompt(config, role, job, run_dir)
        write_json(run_dir / "jobs/A-Correcter-r1.json", job, compact=True)
        (run_dir / "jobs/A-Correcter-r1.md").write_text(prompt, encoding="utf-8")
        status_call("running", role, {"round": 1, "writer_version": version})
        payload = agent_call(role, 1, job, prompt, metrics)
        validate_envelope(payload, job)
        validate_agent_payload(role, payload, run_dir, config)
        payload["writer_run_id"] = run_id
        payload["writer_version"] = version
        payload["writer_paper_sha256"] = manifest_hash(tree_manifest(run_dir / "Paper"))
        write_json(run_dir / OUTPUT_FILES[role], payload)
        _write_completion_checkpoint(run_dir, job, prompt, payload, metrics)
        _publish_outputs(outputs, run_dir, role, payload)
        status_call("finished", role, {"feedback_count": len(payload["feedback"]), "writer_version": version})
        return payload
    except (WorkflowError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        fallback = {**base, "status": "unavailable",
                    "summary": "A-Correcter feedback was unavailable; the validated Writer version remains complete.",
                    "feedback": [], "queries": [], "limitations": [str(exc)[:1000]],
                    "writer_run_id": run_id, "writer_version": version}
        try:
            write_json(run_dir / OUTPUT_FILES[role], fallback)
            _publish_outputs(outputs, run_dir, role, fallback)
        except (OSError, ValueError):
            pass
        status_call("feedback_unavailable", role, {"reason": str(exc)[:1000], "writer_version": version})
        print(f"[workflow] A-Correcter feedback unavailable; Writer {version} remains valid: {exc}",
              file=sys.stderr)
        return fallback


def _initial_manifest(run_dir: Path) -> dict[str, str]:
    path = run_dir / "source.manifest.json"
    return load_json(path)


def validate_manuscript_invariants(paper: Path, changed_files: list[str],
                                   revision_macro: str = "writerrevision") -> None:
    main = paper / "Work-In-Progress/main.tex"
    text = main.read_text(encoding="utf-8")
    if "\\begin{abstract}" not in text:
        raise WorkflowError("Main TeX is missing \\begin{abstract}")
    baseline_main = paper.parent / "source-main.tex"
    if baseline_main.is_file():
        before = baseline_main.read_text(encoding="utf-8")
        if before.split("\\begin{abstract}", 1)[0] != text.split("\\begin{abstract}", 1)[0]:
            raise WorkflowError("Writer changed main-file content before the abstract")
        notation = _notation_section(before)
        if notation and notation not in text:
            raise WorkflowError("Writer changed or removed existing Appendix Notation content")
    prose_files = {"Work-In-Progress/main.tex",
                   "Work-In-Progress/LatexInclusion/Local-Introduction.tex"}
    for relative in prose_files & set(changed_files):
        old_path = paper.parent / "source-writer-files" / relative
        new_path = paper / relative
        if old_path.is_file() and new_path.is_file():
            old_text = old_path.read_text(encoding="utf-8")
            new_text = new_path.read_text(encoding="utf-8")
            # Rotating the prior run's current marker to the previous marker is
            # an expected metadata-only change, not new prose requiring a fresh
            # current-run marker.
            rotated_old = old_text.replace(r"\writerrevision{", r"\writerpreviousrevision{")
            if rotated_old == new_text:
                continue
            diff = difflib.unified_diff(old_text.splitlines(), new_text.splitlines())
            added = "\\n".join(line[1:] for line in diff if line.startswith("+") and not line.startswith("+++"))
            if not added or f"\\{revision_macro}{{" not in added:
                raise WorkflowError(f"New/revised prose in {relative} must be wrapped in the \\{revision_macro}{{...}} macro")


def _notation_section(text: str) -> str:
    match = re.search(r"\\section\*?\{Notation\}.*?(?=\\section\*?\{|\\appendix|\\end\{document\}|\Z)", text, flags=re.S | re.I)
    return match.group(0) if match else ""


def _build_job(config: dict, run_id: str, run_dir: Path, paper_hash: str,
               revision_macros: list[str] | None = None) -> dict:
    return {
        "schema_version": 2,
        "run_id": run_id,
        "stage": "final_build",
        "round": 1,
        "snapshot_sha256": paper_hash,
        "worktree_sha256": manifest_hash(tree_manifest(run_dir / "Paper")),
        "inputs": {},
        "main_tex": "Paper/Work-In-Progress/main.tex",
        "revision_macros": revision_macros or ["writerrevision"],
        "build_variants": ["normal", "highlight_disabled"],
        "build_argv": ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
                       "-file-line-error", "-outdir={output_dir}", "{main_tex}"],
        "prune_duplicate_bib": False,
        "permissions": {"read_only": ["Paper"], "write": ["build/final_build"],
                        "network": "none", "tools": ["approved_latex_build"]},
        "limits": {"stage_timeout_sec": config["limits"]["build_timeout_sec"],
                   "max_stream_bytes": config["limits"]["max_stream_bytes"],
                   "max_output_tokens": 1000, "max_tool_calls": 0},
    }


def live_build(config: dict, run_id: str, run_dir: Path, paper_hash: str,
               launcher_argv: list[str], revision_macros: list[str] | None = None) -> dict:
    job = _build_job(config, run_id, run_dir, paper_hash, revision_macros)
    job_path = run_dir / "jobs/final_build.json"
    write_json(job_path, job, compact=True)
    check_out = run_dir / "logs/final_build.check.stdout"
    check_err = run_dir / "logs/final_build.check.stderr"
    code, output = _run_bounded([*launcher_argv, "check", str(job_path)], cwd=run_dir,
                                timeout=config["limits"]["preflight_timeout_sec"],
                                byte_limit=512_000, stdout_path=check_out, stderr_path=check_err,
                                label="preflight LaTeX build")
    if code:
        raise WorkflowError(f"Isolated LaTeX preflight failed (exit {code}); see {check_err}")
    _check_report(output, job)
    out, err = run_dir / "logs/final_build.stdout", run_dir / "logs/final_build.stderr"
    code, stdout = _run_bounded([*launcher_argv, "run", str(job_path), str(job_path)], cwd=run_dir,
                                timeout=config["limits"]["build_timeout_sec"],
                                byte_limit=config["limits"]["max_stream_bytes"],
                                stdout_path=out, stderr_path=err, label="A-Writer trusted build")
    if code:
        raise WorkflowError(f"A-Writer build failed with status {code}; see {err}")
    try:
        result = load_json_from_text(stdout)
    except ValueError as exc:
        raise WorkflowError(f"LaTeX launcher returned invalid JSON: {exc}") from exc
    reports = result.get("reports")
    if not isinstance(reports, list) or {item.get("variant") for item in reports} != {"normal", "highlight_disabled"}:
        raise WorkflowError("Build must produce normal and highlight-disabled PDFs")
    for report in reports:
        ref = report.get("pdf", {})
        rel = Path(ref.get("path", ""))
        pdf = run_dir / rel
        if report.get("exit_code") != 0 or rel.is_absolute() or ".." in rel.parts or not pdf.is_file():
            raise WorkflowError(f"Build did not produce a valid {report.get('variant')} PDF")
        if not pdf.read_bytes().startswith(b"%PDF-") or sha256_file(pdf) != ref.get("sha256"):
            raise WorkflowError(f"Build PDF hash/header check failed for {report.get('variant')}")
        log_ref = report.get("log", {})
        log_rel = Path(log_ref.get("path", ""))
        log = run_dir / log_rel
        if log_rel.is_absolute() or ".." in log_rel.parts or not log.is_file() or sha256_file(log) != log_ref.get("sha256"):
            raise WorkflowError(f"Build log is missing or failed its hash check for {report.get('variant')}")
        log_text = log.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(^!|Fatal error|Emergency stop|undefined references|undefined citations|Citation .+ undefined|Reference .+ undefined)", log_text, re.I | re.M):
            raise WorkflowError(f"LaTeX {report.get('variant')} build has a fatal error or unresolved citation/reference")
    normal = next(r for r in reports if r["variant"] == "normal")
    normal_pdf = run_dir / normal["pdf"]["path"]
    shutil.copy2(normal_pdf, run_dir / "Paper/Work-In-Progress/main.pdf")
    return {"summary": result.get("summary", "Isolated LaTeX build succeeded"),
            "normal_pdf_sha256": sha256_file(normal_pdf),
            "highlight_disabled_pdf_sha256": next(r["pdf"]["sha256"] for r in reports if r["variant"] == "highlight_disabled"),
            "normal_pdf": "Paper/Work-In-Progress/main.pdf"}


def _prepare_version_log(versions: Path, version: str, run_id: str,
                         researcher: dict, writer: dict, build: dict) -> str:
    idea_ids = [idea["id"] for idea in researcher.get("ideas", [])]
    heading = f"\n## {version} — {utc_now()}\n\n"
    entry = (f"- **Run:** `{run_id}`\n"
             f"- **Researcher ideas integrated:** {', '.join(idea_ids)}\n"
             f"- **Writer summary:** {writer['summary'].strip()}\n"
             f"- **Manuscript files changed:** {', '.join(writer['changed_files'])}\n"
             f"- **PDF:** `Paper/Work-In-Progress/main.pdf` (SHA-256 `{build['normal_pdf_sha256']}`)\n"
             f"- **Build:** normal and highlight-disabled variants succeeded in the isolated LaTeX sandbox\n")
    current = versions / "version.md"
    if current.exists():
        base = current.read_text(encoding="utf-8")
    else:
        base = ("# AI Versions Registry\n\n"
                "Historical V1–V4 are preserved in their original layout. New workflow snapshots use `Vn/Paper/`.\n")
    return base.rstrip() + heading + entry


def commit_and_archive(config: dict, run_id: str, run_dir: Path,
                       initial_project_manifest: dict[str, str], result: dict) -> str:
    paper = ROOT / config["paths"]["paper"]
    versions = ROOT / config["paths"]["versions"]
    final_manifest = tree_manifest(run_dir / "Paper")
    original = initial_project_manifest
    changed = sorted(path for path in set(original) | set(final_manifest) if original.get(path) != final_manifest.get(path))
    expected = set(config["writer_files"]) | {"Work-In-Progress/main.pdf"}
    if not set(changed) <= expected:
        raise WorkflowError("Final Paper snapshot contains unexpected changes: " + repr(changed))
    current = tree_manifest(paper)
    if current != original:
        raise WorkflowError("Live Paper changed during the run; refusing to overwrite concurrent edits")
    version = next_version(versions)
    final_version = versions / version
    if final_version.exists():
        raise WorkflowError(f"Refusing to overwrite existing version {final_version}")
    versions.mkdir(parents=True, exist_ok=True)
    stage = versions / f".{version}.{run_id}.tmp"
    if stage.exists():
        raise WorkflowError(f"Version staging folder already exists: {stage}")
    try:
        shutil.copytree(run_dir / "Paper", stage / "Paper", ignore=shutil.ignore_patterns(
            ".DS_Store", ".venv", "__pycache__", "*.aux", "*.log", "*.fls", "*.fdb_latexmk",
            "*.blg", "*.bbl", "*.out", "*.toc", "*.dvi", "*.synctex.gz"))
        if tree_manifest(stage / "Paper") != final_manifest:
            raise WorkflowError("Version snapshot hash differs from the finished run paper")
        new_log = _prepare_version_log(versions, version, run_id, result["researcher"], result["writer"], result["build"])
        log_temp = versions / "version.md.tmp"
        log_temp.write_text(new_log, encoding="utf-8")
        rollback = run_dir / "rollback"
        rollback.mkdir(exist_ok=True)
        commit_paths = sorted(path for path in changed if path in expected)
        for relative in commit_paths:
            source = run_dir / "Paper" / relative
            target = paper / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = rollback / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.copy2(target, backup)
            else:
                (rollback / (relative + ".missing")).parent.mkdir(parents=True, exist_ok=True)
                (rollback / (relative + ".missing")).write_text("", encoding="utf-8")
        replaced = []
        try:
            for relative in commit_paths:
                source = run_dir / "Paper" / relative
                target = paper / relative
                temp = target.with_name(target.name + ".workflow-tmp")
                shutil.copy2(source, temp)
                os.replace(temp, target)
                replaced.append(relative)
            os.replace(stage, final_version)
            os.replace(log_temp, versions / "version.md")
        except BaseException:
            for relative in reversed(replaced):
                target = paper / relative
                backup = rollback / relative
                missing = rollback / (relative + ".missing")
                if missing.exists():
                    target.unlink(missing_ok=True)
                    missing.unlink()
                elif backup.exists():
                    shutil.copy2(backup, target)
            shutil.rmtree(final_version, ignore_errors=True)
            raise
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        (versions / "version.md.tmp").unlink(missing_ok=True)
        raise
    return version


def _status_path(outputs: Path) -> Path:
    return outputs / "run-status.json"


def _record_status(outputs: Path, run_dir: Path, state: dict, agent: str, details: dict | None = None) -> None:
    at = utc_now()
    state["updated_at"] = at
    state["current_agent"] = agent
    event = {"at": at, "agent": agent, "state": state["status"]}
    if details:
        event["details"] = details
    state.setdefault("history", []).append(event)
    write_json(run_dir / "run.json", state)
    write_json(_status_path(outputs), state)


def _new_run_id(outputs: Path) -> str:
    """Reserve the next sortable numeric ID; caller holds the workflow run lock."""
    runs = outputs / "runs"
    entries = list(runs.iterdir()) if runs.is_dir() else []
    existing_numbers = [int(match.group(1)) for entry in entries
                        if (match := re.fullmatch(r"run-(\d+)", entry.name))]
    sequence_path = outputs / "run-sequence.json"
    last_number = 0
    if sequence_path.exists():
        sequence = load_json(sequence_path)
        if not isinstance(sequence, dict) or sequence.get("schema_version") != 1:
            raise WorkflowError(f"Invalid run sequence record: {sequence_path}")
        last_number = sequence.get("last_number")
        if type(last_number) is not int or last_number < 0:
            raise WorkflowError(f"Invalid run sequence record: {sequence_path}")
    number = max(last_number, len(entries), max(existing_numbers, default=0)) + 1
    while (runs / f"run-{number:06d}").exists():
        number += 1
    write_json(sequence_path, {"schema_version": 1, "last_number": number})
    return f"run-{number:06d}"


def _validated_researcher_comments(comments: str | None) -> str:
    if comments is None:
        return ""
    if not isinstance(comments, str):
        raise WorkflowError("Researcher comments must be text")
    if len(comments.encode("utf-8")) > MAX_RESEARCHER_COMMENTS_BYTES:
        raise WorkflowError(f"Researcher comments must be <= {MAX_RESEARCHER_COMMENTS_BYTES} UTF-8 bytes")
    return comments.strip()


def _read_researcher_comments(text: str | None = None, file_path: str | None = None) -> str:
    if text is not None and file_path is not None:
        raise WorkflowError("Use either --researcher-comments or --researcher-comments-file, not both")
    if file_path is not None:
        path = Path(file_path)
        if path.stat().st_size > MAX_RESEARCHER_COMMENTS_BYTES:
            raise WorkflowError(f"Researcher comments file must be <= {MAX_RESEARCHER_COMMENTS_BYTES} UTF-8 bytes")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkflowError("Researcher comments file must be valid UTF-8") from exc
    return _validated_researcher_comments(text)


def _default_research_brief(config: dict) -> str:
    main_tex = ROOT / config["paths"]["main_tex"]
    manuscript = main_tex.read_text(encoding="utf-8") if main_tex.is_file() else ""
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", manuscript, flags=re.S)
    context = " ".join(match.group(1).split()) if match else ""
    context = context.encode("utf-8")[:2200].decode("utf-8", errors="ignore")
    if context:
        return ("Find actionable, source-supported improvements to the manuscript described by this abstract. "
                "Forward correctness repairs, scope clarifications, modest incremental developments, and new results; novelty is not required. Abstract: " + context)
    return ("Find actionable, source-supported improvements to the current manuscript, including corrections and modest developments. "
            "Novelty is not an acceptance condition.")


def _profiling_config(config: dict) -> dict:
    """Return a one-run measurement configuration without changing the normal config."""
    profiled = copy.deepcopy(config)
    limits = profiled["limits"]
    limits.update({
        "stage_timeout_sec": 3600,
        "preflight_timeout_sec": 180,
        "build_timeout_sec": 900,
        "max_stream_bytes": 67108864,
        "max_artifact_bytes": 1048576,
        "max_total_input_tokens": 10000000,
        "max_total_output_tokens": 1000000,
        "max_cost_usd": 100.0,
        "max_total_download_bytes": 524288000,
    })
    profiled["profiling"] = {"enabled": True, "safety_profile": "raised-finite-observation"}
    return profiled


def _write_profiling_report(run_dir: Path, status: dict) -> None:
    if not run_dir:
        return
    write_json(run_dir / "profiling-report.json", {
        "schema_version": 1,
        "run_id": status.get("run_id"),
        "profiling": status.get("profiling"),
        "outcome": status.get("status"),
        "started_at": status.get("started_at"),
        "updated_at": status.get("updated_at"),
        "decision": status.get("decision"),
        "error": status.get("error"),
        "failed_stage": status.get("failed_stage"),
        "metrics": status.get("metrics", {}),
        "history": status.get("history", []),
    })


def run_workflow(config: dict, research_brief: str | None = None,
                 profiling: bool = False, researcher_comments: str | None = None) -> int:
    if profiling:
        config = _profiling_config(config)
    if research_brief is not None and (not isinstance(research_brief, str) or len(research_brief.encode("utf-8")) > 4000):
        raise WorkflowError("research brief must be text <= 4000 UTF-8 bytes")
    research_brief = (research_brief or "").strip() or _default_research_brief(config)
    researcher_comments = _validated_researcher_comments(researcher_comments)
    outputs = ROOT / config["paths"]["outputs"]
    lock = run_lock(outputs)
    try:
        run_id = _new_run_id(outputs)
    except BaseException:
        lock.close()
        raise
    run_dir = None
    status = {"schema_version": 1, "run_id": run_id, "status": "starting",
              "started_at": utc_now(), "updated_at": utc_now(), "current_agent": "preflight",
              "base_cost_cap_usd": float(config["limits"]["max_cost_usd"]),
              "effective_cost_cap_usd": float(config["limits"]["max_cost_usd"]),
              "resume_extra_cost_usd": 0.0, "config_sha256": sha256_file(CONFIG_FILE),
              "decision": None, "version": None, "research_brief": research_brief,
              "researcher_comments": researcher_comments, "history": [],
              "metrics": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                          "provider_cost_usd": 0.0, "tool_calls": 0, "cost_complete": True,
                          "roles": {}}
    }
    if profiling:
        status["profiling"] = config["profiling"]
    try:
        run_dir, original_manifest = create_run(config, run_id, outputs)
        write_json(run_dir / "source.manifest.json", original_manifest, compact=True)
        write_json(run_dir / "run.json", status)
        print(f"[workflow] Starting full run {run_id}", flush=True)
        paper_hash = manifest_hash(original_manifest)
        status["paper_sha256"] = paper_hash
        status["status"] = "preflight"
        _record_status(outputs, run_dir, status, "preflight")
        launcher_argv, runtime = _runtime_args(config)
        preflight_report = _preflight_roles(config, run_dir, launcher_argv, runtime, announce=True)
        status["preflight"] = preflight_report

        def status_call(new_status: str, agent: str, details: dict | None = None):
            status["status"] = new_status
            if new_status == "running" and details:
                status["active_stage"] = agent
                status["active_round"] = details.get("round")
            if new_status == "decision" and details:
                status["decision"] = details
            elif new_status in {"unsatisfactory", "scout_incomplete", "incomplete", "completed", "failed"}:
                status["decision"] = details or status.get("decision")
            if details and "metrics" in details:
                status["metrics"].update(details["metrics"])
            _record_status(outputs, run_dir, status, agent, details)
            if new_status == "running":
                settings = config["roles"].get(agent) or config["standalone_roles"].get(agent)
                model = settings["model"] if settings else "trusted build"
                print(f"[{agent}] RUNNING — {model} (round {details.get('round')})", flush=True)
            elif new_status == "finished":
                print(f"[{agent}] finished", flush=True)
            elif new_status == "revision":
                if agent == "A-Scout":
                    print("[A-Scout] one bounded source-retrieval retry requested", flush=True)
                else:
                    print(f"[{agent}] one bounded revision requested", flush=True)
            elif new_status == "building":
                print("[A-Writer build] RUNNING — isolated normal + highlight-disabled LaTeX builds", flush=True)

        def agent_call(role, round_number, job, prompt, shared_metrics):
            def progress(event, details):
                if event == "tool":
                    print(f"[{role}] tool {details['tool']} ({details['count']})", flush=True)
            started = time.monotonic()
            before = dict(shared_metrics)
            try:
                return invoke_agent(config, run_dir, job, prompt, launcher_argv,
                                    shared_metrics, progress)
            finally:
                if profiling:
                    role_metrics = shared_metrics.setdefault("roles", {}).setdefault(role, {})
                    role_metrics.update({
                        "elapsed_sec": round(time.monotonic() - started, 3),
                        "input_tokens": shared_metrics.get("input_tokens", 0) - before.get("input_tokens", 0),
                        "output_tokens": shared_metrics.get("output_tokens", 0) - before.get("output_tokens", 0),
                        "total_tokens": shared_metrics.get("total_tokens", 0) - before.get("total_tokens", 0),
                        "provider_cost_usd": round(shared_metrics.get("provider_cost_usd", 0.0) - before.get("provider_cost_usd", 0.0), 8),
                        "tool_calls": shared_metrics.get("tool_calls", 0) - before.get("tool_calls", 0),
                        "cost_complete": shared_metrics.get("cost_complete", False),
                    })

        def build_call(worktree):
            return live_build(config, run_id, worktree, paper_hash, launcher_argv)

        result = execute_pipeline(config, run_id, run_dir, outputs, paper_hash,
                                  agent_call, build_call, status_call, metrics=status["metrics"],
                                  research_brief=research_brief,
                                  researcher_comments=researcher_comments)
        status["metrics"] = result["metrics"]
        if result["outcome"] == "scout_incomplete":
            status["status"] = "incomplete"
            status["error"] = result["reason"]
            status["decision"] = {"agent": "A-Scout", "status": "partial"}
            _record_status(outputs, run_dir, status, "A-Scout", {"error": result["reason"]})
            print(f"[workflow] stopped before Researcher: {result['reason']}", file=sys.stderr)
            return 2
        status["status"] = "finalizing"
        _record_status(outputs, run_dir, status, "A-Writer")
        version = commit_and_archive(config, run_id, run_dir, original_manifest, result)
        result["writer"]["version"] = version
        result["writer"]["version_path"] = f"AI-Versions/{version}/Paper"
        result["writer"]["run_id"] = run_id
        _publish_outputs(outputs, run_dir, "A-Writer", result["writer"])
        feedback = _run_correcter_feedback(config, run_id, run_dir, outputs, paper_hash, version,
                                           status["metrics"], agent_call, status_call)
        result["correcter_feedback"] = feedback
        status["correcter_feedback_status"] = feedback.get("status")
        status["status"] = "completed"
        status["version"] = version
        status["decision"] = {"decision": "WRITER_BUILT", "idea_ids": result["writer"]["integrated_idea_ids"]}
        status["metrics"] = result["metrics"]
        _record_status(outputs, run_dir, status, "A-Correcter", {"version": version, "feedback_status": feedback.get("status")})
        print(f"[workflow] COMPLETE — {version} saved to AI-Versions/{version}/Paper; working Paper updated.", flush=True)
        return 0
    except KeyboardInterrupt:
        status["status"] = "cancelled"
        status["error"] = "Cancelled by operator; any incomplete model usage is unknown."
        status["metrics"]["cost_complete"] = False
        if run_dir:
            _record_status(outputs, run_dir, status, status.get("current_agent", "workflow"), {"error": status["error"]})
        print("\n[workflow] CANCELLED; active child processes were terminated.", file=sys.stderr)
        return 130
    except (WorkflowError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        status["status"] = "failed"
        status["error"] = str(exc)
        status["failed_stage"] = {"agent": status.get("active_stage", status.get("current_agent")),
                                  "round": status.get("active_round")}
        if run_dir:
            _record_status(outputs, run_dir, status, status.get("current_agent", "workflow"), {"error": str(exc)})
        print(f"[workflow] FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if profiling and run_dir:
            _write_profiling_report(run_dir, status)
        lock.close()


def _recover_legacy_checkpoint(config: dict, run_dir: Path, status: dict,
                               role: str, round_number: int) -> dict:
    """Recover a stage boundary from pre-checkpoint runs without trusting mutable inputs."""
    if role not in {"A-Researcher", "A-Writer"}:
        raise WorkflowError("Only failed Researcher/Writer stages can be recovered")
    job_path = run_dir / "jobs" / f"{role}-r{round_number}.json"
    prompt_path = run_dir / "jobs" / f"{role}-r{round_number}.md"
    if not job_path.is_file() or not prompt_path.is_file():
        raise WorkflowError("No saved job/prompt exists for the failed stage; this run cannot be resumed")
    job = load_json(job_path)
    expected = _agent_job(config, status["run_id"], run_dir, role, round_number,
                          status["paper_sha256"], research_brief=status.get("research_brief", ""),
                          researcher_comments=status.get("researcher_comments", ""))
    legacy_writer_job = role == "A-Writer" and job.get("writer_comments_version") is None
    for key in ("schema_version", "run_id", "agent", "stage", "round", "paper_sha256",
                "research_brief", "researcher_comments", "writer_comments_version", "model", "permissions", "limits"):
        if legacy_writer_job and key in {"researcher_comments", "writer_comments_version"}:
            continue  # legacy Writer jobs predate comments being shown to Writer
        if key == "researcher_comments" and key not in job and expected.get(key) == "":
            continue  # legacy runs predate this optional field
        if job.get(key) != expected.get(key):
            raise WorkflowError(f"Saved {role} job differs from current workflow settings ({key})")
    if input_hashes(run_dir, list(job.get("input_hashes", {}))) != job.get("input_hashes"):
        raise WorkflowError("Saved stage input hashes no longer match the run artifacts")
    if role == "A-Writer":
        researcher = load_json(run_dir / OUTPUT_FILES["A-Researcher"])
        if researcher.get("agent") != "A-Researcher" or researcher.get("round") != 1:
            raise WorkflowError("Cannot recover Writer checkpoint without the validated Researcher handoff")
    checkpoint = {
        "schema_version": 1, "run_id": status["run_id"], "next_stage": role,
        "round": round_number, "created_at": utc_now(), "paper_sha256": status["paper_sha256"],
        "job": job, "prompt_sha256": sha256_file(prompt_path),
        "metrics_before_stage": dict(status.get("metrics", {})),
        "recovered_from_legacy_run": True,
    }
    path = _checkpoint_path(run_dir, role, round_number)
    write_json(path, checkpoint)
    return checkpoint


def _resume_target(run_dir: Path, status: dict) -> tuple[str, int]:
    failed = status.get("failed_stage") or {}
    role = failed.get("agent") or status.get("active_stage") or status.get("current_agent")
    round_number = failed.get("round") or status.get("active_round")
    if role not in {"A-Researcher", "A-Writer"}:
        raise WorkflowError("This failed run did not stop at a resumable Researcher or Writer stage")
    if type(round_number) is int and round_number > 0:
        return role, round_number
    candidates = []
    for path in (run_dir / "jobs").glob(f"{role}-r*.json"):
        match = re.fullmatch(re.escape(role) + r"-r([1-9][0-9]*)\.json", path.name)
        if match and (run_dir / "jobs" / (path.stem + ".md")).is_file():
            candidates.append(int(match.group(1)))
    if not candidates:
        raise WorkflowError("Could not identify the failed stage round from saved jobs")
    return role, max(candidates)


def resume_workflow(config: dict, run_id: str, additional_cost_usd: float) -> int:
    """Resume a failed Researcher or Writer stage from its validated checkpoint."""
    run_id = _safe_id(run_id)
    maximum_extra = float(config["limits"].get("max_resume_extra_cost_usd", 0))
    if not isinstance(additional_cost_usd, (int, float)) or not math.isfinite(additional_cost_usd):
        raise WorkflowError("additional cost allowance must be a finite number")
    if additional_cost_usd < 0 or additional_cost_usd > maximum_extra:
        raise WorkflowError(f"additional cost allowance must be >= 0 and <= ${maximum_extra:.2f}")
    outputs = ROOT / config["paths"]["outputs"]
    lock = run_lock(outputs)
    run_dir = outputs / "runs" / run_id
    status = None
    try:
        if not run_dir.is_dir() or not (run_dir / "run.json").is_file():
            raise WorkflowError(f"Unknown run ID: {run_id}")
        status = load_json(run_dir / "run.json")
        if status.get("status") != "failed":
            raise WorkflowError("Only a failed Researcher/Writer stage can be resumed")
        role, round_number = _resume_target(run_dir, status)
        writer_build_retry = _writer_build_failure(status)
        if additional_cost_usd == 0 and not writer_build_retry:
            raise WorkflowError("additional cost allowance must be > 0 unless resuming a completed Writer build")
        writer_payload = None
        if writer_build_retry:
            job, prompt, writer_payload = _load_writer_build_recovery(config, run_dir, status)
        else:
            checkpoint_path = _checkpoint_path(run_dir, role, round_number)
            if checkpoint_path.is_file():
                checkpoint = load_json(checkpoint_path)
            else:
                checkpoint = _recover_legacy_checkpoint(config, run_dir, status, role, round_number)
            job, prompt = _validate_stage_checkpoint(run_dir, checkpoint, status)
        # Permit an explicit cap-increase recovery: the checkpoint still binds
        # manuscript, prompt, and input hashes, while output/cost ceilings may be
        # raised for the retry without changing scientific inputs.
        role_cfg = config["roles"].get(job["agent"]) or config["standalone_roles"].get(job["agent"])
        job["model"] = {"model": role_cfg["model"], "thinking": role_cfg["thinking"]}
        job["limits"]["max_output_tokens"] = role_cfg["max_output_tokens"]
        job["limits"]["max_stream_bytes"] = config["limits"]["max_stream_bytes"]
        job["limits"]["stage_timeout_sec"] = config["limits"]["stage_timeout_sec"]
        job["limits"]["per_tool_timeout_sec"] = 300

        base_cap = float(status.get("base_cost_cap_usd", config["limits"]["max_cost_usd"]))
        if not math.isclose(base_cap, float(config["limits"]["max_cost_usd"]), rel_tol=0, abs_tol=1e-9):
            raise WorkflowError("The run's base cost cap differs from current config")
        used_extension = float(status.get("resume_extra_cost_usd", 0.0))
        cumulative_extension = used_extension + float(additional_cost_usd)
        if cumulative_extension > maximum_extra + 1e-9:
            raise WorkflowError(f"Cumulative resume allowance cannot exceed ${maximum_extra:.2f}")
        effective_cap = base_cap + cumulative_extension
        metrics = status.get("metrics") or {}
        for key, default in (("input_tokens", 0), ("output_tokens", 0), ("total_tokens", 0),
                             ("provider_cost_usd", 0.0), ("tool_calls", 0), ("cost_complete", False)):
            metrics.setdefault(key, default)
        if metrics["provider_cost_usd"] >= effective_cap:
            raise WorkflowError("Reported run cost already exhausts the resumed total cap")
        # Recovery permits controller cap increases; all checkpoint-bound
        # manuscript, prompt, and input hashes remain mandatory above.
        if manifest_hash(tree_manifest(ROOT / config["paths"]["paper"])) != status.get("paper_sha256"):
            raise WorkflowError("Current manuscript differs from the failed run snapshot")

        attempt = len(status.get("resume_authorizations", [])) + 1
        status["previous_error"] = status.get("error")
        status["error"] = None
        status["status"] = "resuming"
        status["base_cost_cap_usd"] = base_cap
        status["resume_extra_cost_usd"] = cumulative_extension
        status["effective_cost_cap_usd"] = effective_cap
        status.setdefault("resume_authorizations", []).append({
            "at": utc_now(), "additional_cost_usd": float(additional_cost_usd),
            "cumulative_extra_cost_usd": cumulative_extension,
            "effective_total_cap_usd": effective_cap,
            "approved_via": "explicit workflow resume command",
        })
        status["active_stage"] = role
        status["active_round"] = round_number
        if writer_build_retry:
            print("[workflow] validated A-Writer output found; retrying only the isolated build", flush=True)
        _record_status(outputs, run_dir, status, role, {
            "resume": True, "round": round_number,
            "additional_cost_usd": float(additional_cost_usd),
            "effective_total_cap_usd": effective_cap,
            "prior_cost_complete": metrics.get("cost_complete", False),
        })

        paper_hash = status["paper_sha256"]
        research_brief = status.get("research_brief", "")
        researcher_comments = status.get("researcher_comments", "")
        resume_config = copy.deepcopy(config)
        resume_config["limits"]["max_cost_usd"] = effective_cap
        launcher_argv, runtime = _runtime_args(config)
        status["preflight"] = _preflight_roles(config, run_dir, launcher_argv, runtime, announce=True)

        def status_call(new_status: str, agent: str, details: dict | None = None):
            status["status"] = new_status
            if new_status == "running" and details:
                status["active_stage"] = agent
                status["active_round"] = details.get("round")
            if details and "decision" in details:
                status["decision"] = details["decision"]
            _record_status(outputs, run_dir, status, agent, details)
            if new_status == "running":
                print(f"[{agent}] RUNNING — {config['roles'][agent]['model']} (round {details.get('round')})", flush=True)

        def call(stage_role: str, stage_round: int, *, saved=False):
            status_call("running", stage_role, {"round": stage_round})
            if saved:
                stage_job, stage_prompt = job, prompt
            else:
                stage_job = _agent_job(config, run_id, run_dir, stage_role, stage_round,
                                       paper_hash, research_brief=research_brief,
                                       researcher_comments=researcher_comments)
                stage_prompt = _prompt(config, stage_role, stage_job, run_dir)
                write_json(run_dir / "jobs" / f"{stage_role}-r{stage_round}.json", stage_job, compact=True)
                (run_dir / "jobs" / f"{stage_role}-r{stage_round}.md").write_text(stage_prompt, encoding="utf-8")
                if stage_role in {"A-Researcher", "A-Writer"}:
                    _write_stage_checkpoint(run_dir, stage_job, stage_prompt, metrics)
            def progress(event, details):
                if event == "tool":
                    print(f"[{stage_role}] tool {details['tool']} ({details['count']})", flush=True)
            payload = invoke_agent(resume_config, run_dir, stage_job, stage_prompt,
                                   launcher_argv, metrics, progress, log_suffix=f"-resume-{attempt}")
            validate_envelope(payload, stage_job)
            validate_agent_payload(stage_role, payload, run_dir, config)
            _write_completion_checkpoint(run_dir, stage_job, stage_prompt, payload, metrics)
            return payload

        if writer_build_retry or role == "A-Writer":
            researcher = load_json(run_dir / OUTPUT_FILES["A-Researcher"])
            researcher_job_path = run_dir / "jobs/A-Researcher-r1.json"
            if not researcher_job_path.is_file():
                raise WorkflowError("Writer resume requires the validated Researcher job")
            researcher_job = load_json(researcher_job_path)
            validate_envelope(researcher, researcher_job)
            validate_agent_payload("A-Researcher", researcher, run_dir, config)
            if job.get("input_hashes", {}).get(OUTPUT_FILES["A-Researcher"]) != sha256_file(run_dir / OUTPUT_FILES["A-Researcher"]):
                raise WorkflowError("Writer checkpoint is not bound to the persisted Researcher handoff")
        else:
            researcher = call("A-Researcher", round_number, saved=True)
            write_json(run_dir / OUTPUT_FILES["A-Researcher"], researcher)
            _persist_research_index(run_dir, researcher, _all_scout_sources(run_dir))
            _publish_outputs(outputs, run_dir, "A-Researcher", researcher)
            status_call("finished", "A-Researcher", {"round": round_number, "idea_count": len(researcher["ideas"])})
        writer = writer_payload if writer_build_retry else call("A-Writer", 1, saved=(role == "A-Writer"))
        expected_ids = [idea["id"] for idea in researcher["ideas"]]
        if writer["integrated_idea_ids"] != expected_ids:
            raise WorkflowError("Writer must integrate every Researcher idea exactly once")
        writer_manifest = tree_manifest(run_dir / "Paper")
        initial = _initial_manifest(run_dir)
        changed = sorted(path for path in set(initial) | set(writer_manifest)
                         if initial.get(path) != writer_manifest.get(path))
        if not changed or not set(changed) <= set(config["writer_files"]):
            raise WorkflowError("Writer made no manuscript changes or changed files outside its five-file allowlist")
        if set(writer["changed_files"]) != set(changed):
            raise WorkflowError("Writer changed_files does not match the actual manuscript diff")
        validate_manuscript_invariants(run_dir / "Paper", changed)
        write_json(run_dir / OUTPUT_FILES["A-Writer"], writer)
        status_call("finished", "A-Writer", {"changed_files": changed})
        status_call("building", "A-Writer", {"variants": ["normal", "highlight_disabled"]})
        build = live_build(config, run_id, run_dir, paper_hash, launcher_argv)
        writer["build"] = build
        write_json(run_dir / OUTPUT_FILES["A-Writer"], writer)
        result = {"outcome": "completed", "scout": load_json(run_dir / OUTPUT_FILES["A-Scout"]),
                  "researcher": researcher, "writer": writer, "build": build,
                  "metrics": metrics, "changed_files": changed}
        status["status"] = "finalizing"
        _record_status(outputs, run_dir, status, "A-Writer")
        version = commit_and_archive(config, run_id, run_dir, load_json(run_dir / "source.manifest.json"), result)
        writer.update({"version": version, "version_path": f"AI-Versions/{version}/Paper", "run_id": run_id})
        _publish_outputs(outputs, run_dir, "A-Writer", writer)
        def feedback_agent_call(stage_role, stage_round, stage_job, stage_prompt, shared_metrics):
            def progress(event, details):
                if event == "tool":
                    print(f"[{stage_role}] tool {details['tool']} ({details['count']})", flush=True)
            return invoke_agent(resume_config, run_dir, stage_job, stage_prompt,
                                launcher_argv, shared_metrics, progress,
                                log_suffix=f"-resume-{attempt}")
        feedback = _run_correcter_feedback(config, run_id, run_dir, outputs, paper_hash, version,
                                           metrics, feedback_agent_call, status_call)
        status["correcter_feedback_status"] = feedback.get("status")
        status["status"] = "completed"
        status.pop("failed_stage", None)
        status["version"] = version
        status["decision"] = {"decision": "WRITER_BUILT", "idea_ids": expected_ids}
        status["metrics"] = metrics
        _record_status(outputs, run_dir, status, "A-Correcter", {
            "version": version, "feedback_status": feedback.get("status"), "build": build})
        return 0
    except KeyboardInterrupt:
        if status is not None:
            status["status"] = "cancelled"
            status["error"] = "Cancelled by operator during resume; incomplete provider usage is unknown."
            status.setdefault("metrics", {})["cost_complete"] = False
            _record_status(outputs, run_dir, status, status.get("active_stage", "workflow"), {"error": status["error"]})
        return 130
    except (WorkflowError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        if status is not None:
            status["status"] = "failed"
            status["error"] = str(exc)
            status["failed_stage"] = {"agent": status.get("active_stage", status.get("current_agent")),
                                      "round": status.get("active_round")}
            _record_status(outputs, run_dir, status, status.get("current_agent", "workflow"), {"error": str(exc)})
        print(f"[workflow] RESUME FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        lock.close()


def show_status(outputs: Path, *, watch=False, interval=1.0) -> int:
    path = _status_path(outputs)
    if not path.is_file():
        print("No workflow run has been recorded yet.")
        return 0
    try:
        last_update = None
        while True:
            state = load_json(path)
            signature = (state.get("updated_at"), len(state.get("history", [])))
            if signature != last_update:
                print(json.dumps(state, ensure_ascii=False, indent=2))
                last_update = signature
            if not watch:
                return 0
            time.sleep(max(0.25, interval))
    except KeyboardInterrupt:
        print("\nStopped watching (workflow is unaffected).")
        return 0


def run_tests() -> int:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "paper_workflow/tests", "-v"]
    return subprocess.run(command, cwd=ROOT).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the Scout→Researcher→Writer→A-Correcter feedback workflow.")
    subs = parser.add_subparsers(dest="command")
    run_parser = subs.add_parser("run", help="Run Scout→Researcher→Writer, then collect non-blocking A-Correcter feedback")
    run_parser.add_argument("--research-brief", help="Optional focused research objective (max 4000 UTF-8 bytes)")
    comments_group = run_parser.add_mutually_exclusive_group()
    comments_group.add_argument("--researcher-comments", help="User topic/priority notes for A-Scout, A-Researcher, and A-Writer (max 4000 UTF-8 bytes)")
    comments_group.add_argument("--researcher-comments-file", help="UTF-8 file containing user topic/priority notes for A-Scout, A-Researcher, and A-Writer (max 4000 bytes)")
    run_parser.add_argument("--profile", action="store_true", help="Run one raised-finite profiling workflow and write profiling-report.json")
    resume_parser = subs.add_parser("resume", help="Resume a failed Researcher/Writer stage from its validated checkpoint")
    resume_parser.add_argument("--run-id", required=True, help="Failed run ID to resume")
    resume_parser.add_argument("--additional-cost-usd", type=float, required=True,
                               help="Budget extension; 0 is allowed for a validated build-only A-Writer retry")
    check_parser = subs.add_parser("check", help="Check Nono isolation and exact model/effort for all configured stages; no agent calls")
    status_parser = subs.add_parser("status", help="Show current workflow status")
    status_parser.add_argument("--watch", action="store_true", help="Poll status until interrupted")
    status_parser.add_argument("--interval", type=float, default=1.0)
    subs.add_parser("test", help="Run offline state-machine, handoff, timeout, and permission tests")
    args = parser.parse_args(argv)
    command = args.command or "run"
    if command == "test":
        return run_tests()
    if command == "status":
        return show_status(ROOT / "Agent-Outputs", watch=args.watch, interval=args.interval)
    try:
        config = load_config()
        if command == "check":
            report = preflight(config)
            print(json.dumps(report, indent=2))
            print("Preflight passed. No research or writing model call was made.")
            return 0
        if command == "resume":
            return resume_workflow(config, args.run_id, args.additional_cost_usd)
        comments = _read_researcher_comments(getattr(args, "researcher_comments", None),
                                             getattr(args, "researcher_comments_file", None))
        return run_workflow(config, getattr(args, "research_brief", None),
                            profiling=getattr(args, "profile", False), researcher_comments=comments)
    except (WorkflowError, OSError, ValueError, KeyError) as exc:
        print(f"[workflow] FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
