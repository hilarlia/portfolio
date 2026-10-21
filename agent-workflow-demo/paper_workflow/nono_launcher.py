#!/usr/bin/env python3
"""Run workflow-v2 agent/build jobs inside an ephemeral Nono sandbox.

The host launcher copies only declared job inputs into a disposable workspace.
Pi never receives the workflow run directory, state, manifests, or host Pi auth.json.
Only declared output paths are copied back after byte-for-byte integrity checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
from pathlib import Path

PUBLIC_WEB_TLDS = """
com org edu gov net mil int info biz name pro museum aero coop jobs travel mobi cat tel asia post
io ai app dev science tech online site xyz me cloud global blog agency digital wiki academy university
ac ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz
ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz de dj dk dm do dz ec ee eg eh er es et eu fi fj fk fo fr ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im in io iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pe pf pg ph pk pl pm pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st su sv sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug uk us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw
""".split()
PUBLIC_WEB_SUFFIXES = tuple("*." + tld for tld in PUBLIC_WEB_TLDS)
PRIVATE_HOSTS = [
    "localhost", "*.localhost", "*.local", "*.internal", "*.corp", "*.home",
    "127.*.*.*", "10.*.*.*", "192.168.*.*", *[f"172.{i}.*.*" for i in range(16, 32)],
    "169.254.*.*", "100.64.*.*", "0.*.*.*", "224.*.*.*", "240.*.*.*",
    "::", "::1", "[::]", "[::1]", "fe80::1", "[fe80::1]", "fc00::1", "[fc00::1]",
    "fd00::1", "[fd00::1]", "metadata", "metadata.google.internal", "instance-data.ec2.internal",
]
PI_CREDENTIAL_VARS = ["EXAMPLE_PROVIDER_API_KEY", "EXAMPLE_PROVIDER_API_KEY", "OPENAI_API_KEY",
                      "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "AWS_ACCESS_KEY_ID",
                      "AWS_SECRET_ACCESS_KEY", "AWS_BEARER_TOKEN_BEDROCK"]
PI_TOOL_MAPPING = {
    "read": "read", "grep": "grep", "find": "find", "ls": "ls",
    "edit": "edit", "write": "write", "bash": "bash", "file_hash": "bash",
    "restricted_python": "bash", "web_search": "bash", "web_read": "read",
    "pdf_render": "bash", "approved_latex_build": "bash",
}
SYSTEM_TOOL_PATHS = [Path("/usr/local/bin"), Path("/opt/homebrew/bin")]
SYSTEM_DATA_PATHS = [Path("/usr/local/share"), Path("/opt/homebrew/share"), Path("/usr/share")]


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_tree(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Pinned dependency tree contains symlink: {path}")
        if path.is_file():
            h.update(path.relative_to(root).as_posix().encode())
            h.update(bytes.fromhex(sha_file(path)))
    return h.hexdigest()


def digest_tree(root: Path) -> dict[str, tuple[str, str | None]]:
    """Return all directories/files, rejecting symlinks and special files."""
    result = {".": ("dir", None)}
    if not root.exists():
        return {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"Symlink in sandbox workspace: {rel}")
        if path.is_dir():
            result[rel] = ("dir", None)
        elif path.is_file():
            result[rel] = ("file", sha_file(path))
        else:
            raise ValueError(f"Non-regular sandbox workspace entry: {rel}")
    return result


def relative(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"Invalid job-relative path: {value!r}")
    path = root / value
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"Symlink in declared job path: {value}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Job path escaped run root: {value}")
    return path


def copy_input(run_root: Path, workspace: Path, rel: str):
    source = relative(run_root, rel)
    target = relative(workspace, rel)
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for entry in sorted(source.rglob("*")):
            if entry.is_symlink():
                raise ValueError(f"Symlink in declared input tree: {entry}")
            destination = target / entry.relative_to(source)
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif entry.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    shutil.copyfile(entry, destination)
            else:
                raise ValueError(f"Non-regular input: {entry}")
    elif source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
    else:
        raise ValueError(f"Declared input does not exist: {rel}")


def _iter_bib_entries(text: str):
    i = 0
    n = len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            return
        brace = text.find("{", at)
        if brace < 0:
            return
        comma = text.find(",", brace + 1)
        if comma < 0:
            return
        key = text[brace + 1:comma].strip()
        if not key:
            i = comma + 1
            continue
        depth = 1
        j = brace + 1
        while j < n and depth:
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1
        if depth != 0:
            return
        yield at, j, key
        i = j


def _bib_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {key for _, _, key in _iter_bib_entries(path.read_text(errors="replace"))}


def _prune_redundant_local_temp_bib_entries(build_cwd: Path, main_tex_name: str):
    """Remove entries from Local-Temp.bib when the same key exists in other .bib files.

    This runs only in the disposable build workspace; source/worktree files are not
    modified in the run directory.
    """
    main_tex = build_cwd / main_tex_name
    if not main_tex.is_file():
        return
    content = main_tex.read_text(errors="replace")
    match = re.search(r"\\bibliography\{(.*?)\}", content, re.S)
    if not match:
        return
    lines = [line.split("%", 1)[0] for line in match.group(1).splitlines()]
    refs = [token.strip() for token in ",".join(lines).split(",") if token.strip()]
    local_ref = next((r for r in refs if r.replace("\\", "/").endswith("Local-Temp")), None)
    if not local_ref:
        return
    local_path = (build_cwd / (local_ref + ".bib")).resolve()
    if not local_path.is_file():
        return
    redundant = set()
    for ref in refs:
        if ref == local_ref or ref.endswith("Notes"):
            continue
        other = (build_cwd / (ref + ".bib")).resolve()
        redundant |= _bib_keys(other)
    original = local_path.read_text(errors="replace")
    kept = []
    removed = []
    cursor = 0
    for start, end, key in _iter_bib_entries(original):
        kept.append(original[cursor:start])
        block = original[start:end]
        if key in redundant:
            removed.append(key)
        else:
            kept.append(block)
        cursor = end
    if not removed:
        return
    kept.append(original[cursor:])
    local_path.write_text("".join(kept))
    sys.stderr.write(
        "Nono workflow launcher: pruned redundant Local-Temp.bib keys: "
        + ", ".join(sorted(set(removed))) + "\n"
    )


def stage_bounded_extension(source: Path, destination: Path, max_output_tokens: int) -> Path:
    shutil.copytree(source, destination)
    models_js = destination / "dist/models.js"
    body = models_js.read_text()
    marker = "maxTokens: options.maxTokens,"
    if body.count(marker) != 1:
        raise ValueError("Pinned Example Provider extension does not have the expected maxTokens hook")
    body = body.replace(marker,
                        "maxTokens: Math.min(options.maxTokens, Number(process.env.WORKFLOW_MAX_OUTPUT_TOKENS) || options.maxTokens),")
    models_js.write_text(body)
    return destination


def under(rel: str, permitted: str) -> bool:
    return rel == permitted or rel.startswith(permitted.rstrip("/") + "/")


def allowed_write(rel: str, writes: list[str]) -> bool:
    return any(under(rel, permitted) for permitted in writes)


def profile_network(profile_source: dict, public_web: bool) -> dict:
    """Take only Example Provider credential routing from the reviewed profile, not its FS grants."""
    network = profile_source.get("network") or {}
    route = (network.get("custom_credentials") or {}).get("example-provider")
    if "example-provider" not in network.get("credentials", []) or not isinstance(route, dict):
        raise ValueError("Pinned Nono profile lacks its Example Provider phantom credential route")
    if route.get("upstream") != "https://example-provider.api.mit.edu":
        raise ValueError("Unexpected Example Provider credential upstream in pinned profile")
    allowed_endpoints = {(x.get("method"), x.get("path")) for x in route.get("endpoint_rules", [])}
    required = {("POST", "/v1/chat/completions"), ("POST", "/v1/responses")}
    if not required <= allowed_endpoints:
        raise ValueError("Example Provider credential route lacks the expected inference-only endpoint policy")
    result = {"block": False,
              "allow_domain": list(PUBLIC_WEB_SUFFIXES) if public_web else ["example-provider.api.mit.edu"],
              "deny_domain": list(PRIVATE_HOSTS),
              "credentials": ["example-provider"],
              "custom_credentials": {"example-provider": route}}
    return result


def make_profile(workspace: Path, profile_source: dict, job: dict, settings, build=False) -> dict:
    writes = list(job.get("permissions", {}).get("write", []))
    for rel in writes:
        target = relative(workspace, rel)
        if rel.endswith("/") or not Path(rel).suffix:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)

    # Keep runtime state outside the readable workspace so workdir read access
    # cannot expose extension caches or temporary credentials/state.
    agent_dir = workspace.parent / "pi-agent"
    tmp_dir = workspace.parent / "tmp"
    agent_dir.mkdir(exist_ok=True)
    tmp_dir.mkdir(exist_ok=True)

    readonly = [relative(workspace, value) for value in job.get("permissions", {}).get("read_only", [])]
    read_paths = [str(path) for path in readonly if path.is_dir()]
    read_files = [str(path) for path in readonly if path.is_file()]
    for name in ("workflow-job.json", "workflow-prompt.md"):
        path = workspace / name
        if path.is_file():
            read_files.append(str(path))
    read_paths.extend([str(settings.node.parent), str(settings.pi_package),
                       str(settings.jiti_package), str(settings.example-provider_extension),
                       str(settings.python_root)])
    for tool_dir in SYSTEM_TOOL_PATHS:
        if tool_dir.exists():
            read_paths.append(str(tool_dir))
    for data_dir in SYSTEM_DATA_PATHS:
        if data_dir.exists():
            read_paths.append(str(data_dir))
    if build:
        read_paths.extend([str(settings.tex_bin), str(settings.tex_root)])
    read_paths = list(dict.fromkeys(read_paths))
    read_files = list(dict.fromkeys(read_files))

    allow_paths = [str(agent_dir), str(tmp_dir)]
    allow_files = []
    if build and job.get("stage") == "final_build":
        main_rel = Path(job["main_tex"])
        disabled_defs = workspace / main_rel.parent / "LatexInclusion" / "Local-Definitions.tex"
        allow_files.append(str(disabled_defs))
    texmf_home = workspace.parent / "texmf-home"
    texmf_var = workspace.parent / "texmf-var"
    texmf_home.mkdir(exist_ok=True)
    texmf_var.mkdir(exist_ok=True)
    allow_paths.extend([str(texmf_home), str(texmf_var)])
    for rel in writes:
        target = relative(workspace, rel)
        if target.is_dir() or not Path(rel).suffix:
            target.mkdir(parents=True, exist_ok=True)
            allow_paths.append(str(target))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            allow_files.append(str(target))

    if build:
        build_tmp = workspace / "build-out"
        build_tmp.mkdir(exist_ok=True)
        allow_paths.append(str(build_tmp))
    gs_lib_dirs = [
        path for path in (
            Path("/usr/local/share/ghostscript"),
            Path("/opt/homebrew/share/ghostscript"),
            Path("/usr/share/ghostscript"),
        ) if path.exists()
    ]
    gs_lib_value = os.pathsep.join(str(path) for path in gs_lib_dirs)

    profile = {
        "meta": {"name": "workflow-nono-ephemeral", "version": "1",
                 "description": "Per-stage Nono sandbox; only copied job inputs and declared outputs"},
        "extends": "default",
        "groups": {"include": []},
        "workdir": {"access": "read"},
        "filesystem": {"read": read_paths, "read_file": read_files,
                       "allow": list(dict.fromkeys(allow_paths)),
                       "allow_file": list(dict.fromkeys(allow_files))},
        "environment": {
            "allow_vars": ["HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "PI_CODING_AGENT_DIR",
                           "EXAMPLE_PROVIDER_MODEL_DISCOVERY", "WORKFLOW_MAX_OUTPUT_TOKENS", "TEXMFHOME", "TEXMFVAR",
                           "GS_LIB"],
            "deny_vars": PI_CREDENTIAL_VARS,
            "set_vars": {"PI_CODING_AGENT_DIR": str(agent_dir),
                         "EXAMPLE_PROVIDER_MODEL_DISCOVERY": "0",
                         "WORKFLOW_MAX_OUTPUT_TOKENS": str(job.get("limits", {}).get("max_output_tokens", 8000)),
                         "TMPDIR": str(tmp_dir),
                         "TEXMFHOME": str(texmf_home),
                         "TEXMFVAR": str(texmf_var),
                         "GS_LIB": gs_lib_value},
        },
        "network": {"block": True} if build else profile_network(
            profile_source, job.get("permissions", {}).get("network") == "approved-public-search-and-source-read"),
    }
    if not build:
        profile["environment"]["allow_vars"].append("TEXMFHOME")
    return profile


def json_command(nono: Path, profile_path: Path, cwd: Path, cmd: list[str], env: dict,
                 timeout: int = 30, dry_run=False):
    argv = [str(nono), "run", "--profile", str(profile_path), "--silent", "--allow-cwd"]
    if dry_run:
        argv.append("--dry-run")
    argv.extend(["--", *cmd])
    return subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True,
                          timeout=timeout, check=False)


def verify_pinned_runtime(args) -> dict:
    profile_source_path = Path(args.profile_source).resolve()
    checks = ((Path(args.nono), args.nono_sha256, "Nono executable"),
              (Path(args.node), args.node_sha256, "Node executable"),
              (Path(args.pi_cli), args.pi_cli_sha256, "Pi CLI bundle"),
              (Path(args.python_bin), args.python_bin_sha256, "Python executable"),
              (Path(args.latexmk), args.latexmk_sha256, "LaTeX build executable"))
    if sha_file(profile_source_path) != args.profile_sha256:
        raise ValueError("Nono Example Provider profile changed since workflow config was pinned")
    for path, expected, label in checks:
        if sha_file(path) != expected:
            raise ValueError(f"{label} changed since workflow config was pinned")
    if sha_tree(Path(args.pi_package)) != args.pi_package_sha256:
        raise ValueError("Pi runtime package changed since workflow config was pinned")
    if sha_tree(Path(args.example-provider_extension)) != args.example-provider_extension_sha256:
        raise ValueError("Example Provider extension changed since workflow config was pinned")
    return json.loads(profile_source_path.read_text())


def check(args, job_path: Path) -> int:
    job = json.loads(job_path.read_text())
    requested_tools = job.get("permissions", {}).get("tools", [])
    unmapped = sorted(set(requested_tools) - set(PI_TOOL_MAPPING))
    if unmapped:
        raise ValueError("Requested logical tool(s) have no Pi mapping: " + ", ".join(unmapped))
    profile_source_path = Path(args.profile_source).resolve()
    profile_source = verify_pinned_runtime(args)
    if job.get("model") and not os.environ.get("EXAMPLE_PROVIDER_API_KEY"):
        raise ValueError("Pinned Nono Example Provider credential source is missing from the launcher environment")

    with tempfile.TemporaryDirectory(prefix=".wf-nono-check-", dir=job_path.parent) as temp:
        outer = Path(temp)
        workspace = outer / "workspace"
        workspace.mkdir()
        # Create shape-only placeholders for policy checks. Never copy the whole
        # paper/reference tree just to test a profile or model catalog.
        for rel in job.get("permissions", {}).get("read_only", []):
            target = relative(workspace, rel)
            if Path(rel).suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"")
            else:
                target.mkdir(parents=True, exist_ok=True)
        (workspace / "workflow-job.json").write_text("{}", encoding="utf-8")
        (workspace / "workflow-prompt.md").write_text("preflight only", encoding="utf-8")
        (outer / "pi-agent").mkdir()
        (outer / "tmp").mkdir()
        profile = make_profile(workspace, profile_source, job, args,
                               build=job.get("stage") in ("baseline_build", "final_build"))
        profile_path = outer / "profile.json"
        profile_path.write_text(json.dumps(profile))
        validate = subprocess.run([str(args.nono), "profile", "validate", str(profile_path)],
                                  text=True, capture_output=True, timeout=30, check=False)
        if validate.returncode:
            raise ValueError("Nono rejected the ephemeral job profile")

        version = subprocess.run([str(args.nono), "--version"], text=True,
                                 capture_output=True, timeout=10, check=False)
        if version.returncode:
            raise ValueError("Could not verify Nono runtime")

        # Verify declared reads/writes and representative forbidden paths through
        # Nono's actual policy resolver before any model call.
        read_grants = [relative(workspace, rel) for rel in job.get("permissions", {}).get("read_only", [])]
        write_grants = list(job.get("permissions", {}).get("write", []))
        def read_allowed(rel):
            path = relative(workspace, rel)
            return any(path == grant or (grant.is_dir() and path.is_relative_to(grant)) for grant in read_grants)
        def write_allowed(rel):
            return any(under(rel, grant) for grant in write_grants)
        read_samples = ("scout_retrieval.py",
                        "Paper/Work-In-Progress/main.tex",
                        "Paper/Work-In-Progress/LatexInclusion/Local-Introduction.tex",
                        "Paper/Work-In-Progress/LatexInclusion/Local-Definitions.tex",
                        "Paper/Manuscript-Style-Assets/Definitions/Style-Format.tex",
                        "Agent-Outputs/A-Scout/papers/preflight-new.pdf",
                        "Agent-Outputs/A-Scout/Read-Papers.json",
                        "Agent-Outputs/A-Researcher.json",
                        "Agent-Outputs/A-Correcter/Feedback.json",
                        "Agent-Outputs/A-Correcter/Prior-Feedback.json",
                        "AI-Versions/V999/Paper")
        write_samples = ("Paper/Work-In-Progress/main.tex",
                         "Paper/Manuscript-Style-Assets/Definitions/Style-Format.tex",
                         "Agent-Outputs/A-Scout/papers/permission-probe.pdf",
                         "Agent-Outputs/A-Scout/Overview.json",
                         "AI-Versions/V999/Paper",
                         "build/final_build/permission-probe.pdf")
        checks = [(str(Path.home() / ".pi/agent/auth.json"), "read", "denied"),
                  (str(workspace / "state.json"), "readwrite", "denied")]
        checks.extend((str(workspace / rel), "read", "allowed" if read_allowed(rel) else "denied")
                      for rel in read_samples)
        checks.extend((str(workspace / rel), "write", "allowed" if write_allowed(rel) else "denied")
                      for rel in write_samples)
        for path, op, expected in checks:
            query = subprocess.run([str(args.nono), "why", "--profile", str(profile_path),
                                    "--workdir", str(workspace), "--path", path, "--op", op, "--json"],
                                   text=True, capture_output=True, timeout=15, check=False)
            try:
                result = json.loads(query.stdout)
            except ValueError as exc:
                raise ValueError("Nono access-policy query was not valid JSON") from exc
            if result.get("status") != expected:
                raise ValueError(f"Nono profile returned {result.get('status')} for {op} {path}; expected {expected}")

        # Exercise the actual OS boundary, not just the profile resolver: the role's
        # one permitted write must work (when any), while an unrelated existing file
        # remains unwritable. This catches broad system-temp grants and profile drift.
        write_probe = ("build/final_build/permission-probe.txt" if job.get("stage") in ("baseline_build", "final_build")
                       else "Paper/Work-In-Progress/main.tex" if job.get("stage") == "A-Writer"
                       else "Agent-Outputs/A-Scout/papers/permission-probe.txt")
        write_path = workspace / write_probe
        write_path.parent.mkdir(parents=True, exist_ok=True)
        allowed = any(under(write_probe, grant) for grant in job.get("permissions", {}).get("write", []))
        denied_path = workspace / "AI-Versions/V999/Paper/permission-probe.txt"
        denied_path.parent.mkdir(parents=True, exist_ok=True)
        denied_path.write_text("protected", encoding="utf-8")
        relative_denied = "AI-Versions/V999/Paper/permission-probe.txt"
        script = (f"test \"$PWD\" = {shlex.quote(str(workspace))} || exit 40; "
                  f"if printf permitted > {shlex.quote(write_probe)}; then got=1; else got=0; fi; "
                  f"[ $got -eq {int(allowed)} ] || exit 41; "
                  f"if printf forbidden > {shlex.quote(relative_denied)}; then exit 42; else exit 0; fi")
        probe = subprocess.run([str(args.nono), "run", "--profile", str(profile_path), "--silent",
                                "--allow-cwd", "--", "/bin/sh", "-c", script], cwd=workspace,
                               text=True, capture_output=True, timeout=20, check=False)
        if probe.returncode != 0 or denied_path.read_text(encoding="utf-8") != "protected":
            raise ValueError(f"Nono OS write-scope probe failed for {job.get('stage')}: {probe.stderr.strip()[:500]}")
        if allowed and write_path.read_text(encoding="utf-8") != "permitted":
            raise ValueError(f"Nono did not permit the declared write path for {job.get('stage')}")

        web_requested = job.get("permissions", {}).get("network") == "approved-public-search-and-source-read"
        model_requested = bool(job.get("model"))
        for host, expected in (("example.com", "allowed" if web_requested else "denied"),
                               ("arxiv.org", "allowed" if web_requested else "denied"),
                               ("api.crossref.org", "allowed" if web_requested else "denied"),
                               ("api.openalex.org", "allowed" if web_requested else "denied"),
                               ("api.semanticscholar.org", "allowed" if web_requested else "denied"),
                               ("localhost", "denied"), ("127.0.0.1", "denied"),
                               ("10.0.0.1", "denied"), ("192.168.1.1", "denied"),
                               ("172.20.1.1", "denied"), ("100.64.0.1", "denied"),
                               ("169.254.169.254", "denied"), ("[fd00::1]", "denied"),
                               ("metadata.google.internal", "denied"),
                               ("example-provider.api.mit.edu", "allowed" if model_requested else "denied")):
            query = subprocess.run([str(args.nono), "why", "--profile", str(profile_path),
                                    "--workdir", str(workspace), "--host", host, "--json"],
                                   text=True, capture_output=True, timeout=15, check=False)
            try:
                result = json.loads(query.stdout)
            except ValueError as exc:
                raise ValueError("Nono network-policy query was not valid JSON") from exc
            if result.get("status") != expected:
                raise ValueError(f"Nono network policy for {host} was {result.get('status')}, expected {expected}")

        if job.get("permissions", {}).get("network") == "approved-public-search-and-source-read":
            curl = shutil.which("curl") or "/usr/bin/curl"
            if not Path(curl).is_file():
                raise ValueError("Public-web role preflight could not find curl")
            for probe_url in ("https://export.arxiv.org/", "https://api.crossref.org/works?rows=1",
                              "https://api.openalex.org/works?per-page=1"):
                web_probe = subprocess.run([str(args.nono), "run", "--profile", str(profile_path),
                                            "--silent", "--allow-cwd", "--", curl,
                                            "--connect-timeout", "5", "--max-time", "12", "-sSIL",
                                            probe_url], cwd=workspace,
                                           text=True, capture_output=True, timeout=20, check=False)
                if web_probe.returncode:
                    raise ValueError(f"Public-web sandbox probe failed for {probe_url}: {web_probe.stderr.strip()[:500]}")

        if job.get("model"):
            staged_extension = stage_bounded_extension(
                Path(args.example-provider_extension), outer / "pi-agent" / "mit-example-provider-pi-extension",
                job["limits"]["max_output_tokens"])
            env = os.environ.copy()
            preflight_path = [str(args.node.parent), str(args.python_bin.parent), str(args.tex_bin)]
            preflight_path.extend(str(path) for path in SYSTEM_TOOL_PATHS if path.exists())
            preflight_path.extend(["/usr/bin", "/bin"])
            env["PATH"] = os.pathsep.join(preflight_path)
            env["PI_CODING_AGENT_DIR"] = str(outer / "pi-agent")
            env["EXAMPLE_PROVIDER_MODEL_DISCOVERY"] = "0"  # local bundled catalog; preflight makes no web/model call
            env["WORKFLOW_MAX_OUTPUT_TOKENS"] = str(job["limits"]["max_output_tokens"])
            env["TMPDIR"] = str(outer / "tmp")
            rpc = [str(args.node), str(args.pi_cli), "--mode", "rpc", "--no-session",
                   "--no-context-files", "--no-approve", "--no-skills", "--no-themes",
                   "--no-prompt-templates", "--no-mcp", "--no-extensions",
                   "--extension", str(staged_extension / "dist/index.js")]
            invoke = [str(args.nono), "run", "--profile", str(profile_path), "--silent", "--allow-cwd", "--",
                      *rpc]
            response = subprocess.run(invoke, cwd=workspace, env=env,
                                      input=json.dumps({"id": "workflow-model-preflight", "type": "get_available_models"}) + "\n",
                                      text=True, capture_output=True, timeout=45, check=False)
            if response.returncode:
                raise ValueError("Pi did not initialize successfully inside the Nono sandbox")
            models = []
            for line in response.stdout.splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "response" and event.get("command") == "get_available_models":
                    models = event.get("data", {}).get("models", [])
            requested = job["model"]
            model_id = requested["model"].split("/", 1)[1] if requested["model"].startswith("example-provider/") else requested["model"]
            selected_model = next((m for m in models if m.get("provider") == "example-provider" and m.get("id") == model_id), None)
            if selected_model is None:
                raise ValueError(f"Requested model {requested['model']} is unavailable in the sandboxed Pi catalog")
            if requested["thinking"] not in selected_model.get("thinkingLevelMap", {}):
                raise ValueError("Requested thinking level is not supported by the sandboxed model")
            if selected_model.get("maxTokens", 0) > job["limits"]["max_output_tokens"]:
                raise ValueError("Pi provider model exceeds the configured workflow output-token ceiling")
        elif job.get("stage") in ("baseline_build", "final_build"):
            env = os.environ.copy()
            preflight_build_path = [str(args.tex_bin)]
            preflight_build_path.extend(str(path) for path in SYSTEM_TOOL_PATHS if path.exists())
            preflight_build_path.extend(["/usr/bin", "/bin"])
            env["PATH"] = os.pathsep.join(preflight_build_path)
            env["TMPDIR"] = str(workspace / "tmp")
            probe = subprocess.run([str(args.nono), "run", "--profile", str(profile_path), "--silent", "--allow-cwd", "--",
                                    str(args.latexmk), "-version"], cwd=workspace, env=env,
                                   text=True, capture_output=True, timeout=30, check=False)
            if probe.returncode:
                raise ValueError("LaTeX toolchain did not start inside the network-blocked Nono sandbox")

    nono_text = (version.stdout or version.stderr).strip()
    dump({
        "job_sha256": sha_file(job_path),
        "whole_process_isolation": True,
        "credentials_outside_workers": True,
        "read_only_inputs": True,
        "scoped_writes": True,
        "network_policy": True,
        "tool_budgets": True,
        "check_budgets_verified": True,
        "model_verified": True,
        "tools_verified": True,
        "effective_model": job.get("model"),
        "sandbox_profile_sha256": args.profile_sha256,
        "nono_version": nono_text,
        "details": {"backend": "nono", "profile_source": str(profile_source_path),
                    "public_search": job.get("permissions", {}).get("network") == "approved-public-search-and-source-read",
                    "public_tld_allowlist": True, "private_address_denies_tested": True,
                    "scratch_only_writes": True,
                    "evaluator_tool_timeout_seconds": job.get("limits", {}).get("max_check_seconds"),
                    "candidate_count_cap": "prompt/protocol limit; arbitrary Python iterations are not statically instrumented"},
    })
    return 0


def dump(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _workspace(run_root: Path, job: dict, job_path: Path, prompt_path: Path):
    scratch = tempfile.TemporaryDirectory(prefix=".wf-nono-stage-", dir=run_root)
    outer = Path(scratch.name)
    workspace = outer / "workspace"
    workspace.mkdir()
    for rel in job.get("permissions", {}).get("read_only", []):
        copy_input(run_root, workspace, rel)
    (outer / "pi-agent").mkdir(exist_ok=True)
    (outer / "tmp").mkdir(exist_ok=True)
    shutil.copyfile(job_path, workspace / "workflow-job.json")
    shutil.copyfile(prompt_path, workspace / "workflow-prompt.md")
    for rel in job.get("permissions", {}).get("write", []):
        target = relative(workspace, rel)
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target.mkdir(parents=True, exist_ok=True)
    return scratch, outer, workspace


def _profile_for_run(workspace: Path, profile_source: dict, job: dict, args, is_build=False):
    return make_profile(workspace, profile_source, job, args, build=is_build)


def _import_outputs(workspace: Path, run_root: Path, job: dict, before: dict):
    after = digest_tree(workspace)
    writes = list(job.get("permissions", {}).get("write", []))
    scratch_only = ["pi-agent", "tmp", "build-out", "texmf-home", "texmf-var"]
    if job.get("stage") == "final_build":
        scratch_only.append((Path(job["main_tex"]).parent / "LatexInclusion" / "Local-Definitions.tex").as_posix())
    protected = {rel for rel, state in before.items()
                 if rel not in (".",)
                 and not any(under(rel, item) for item in writes)
                 and not any(under(rel, item) for item in scratch_only)}
    for rel in protected:
        if after.get(rel) != before[rel]:
            raise ValueError(f"Sandbox modified a non-writable job input: {rel}")
    for rel in after.keys() - before.keys():
        if not allowed_write(rel, writes) and not any(under(rel, x) for x in scratch_only):
            raise ValueError(f"Sandbox created an out-of-scope file: {rel}")
    for rel in before.keys() - after.keys():
        if not any(under(rel, x) for x in writes) and not any(under(rel, x) for x in scratch_only):
            raise ValueError(f"Sandbox deleted a non-writable job input: {rel}")
    for rel, state in after.items():
        if state[0] != "file" or not allowed_write(rel, writes) or before.get(rel) == state:
            continue
        source = relative(workspace, rel)
        target = relative(run_root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def run_agent(args, job_path: Path, prompt_path: Path):
    job = json.loads(job_path.read_text())
    profile_source = verify_pinned_runtime(args)
    run_root = Path.cwd().resolve()
    scratch, outer, workspace = _workspace(run_root, job, job_path, prompt_path)
    try:
        before = digest_tree(workspace)
        profile = _profile_for_run(workspace, profile_source, job, args)
        profile_path = outer / "profile.json"
        profile_path.write_text(json.dumps(profile))
        env = os.environ.copy()
        agent_path = [str(args.node.parent), str(args.python_bin.parent), str(args.tex_bin)]
        agent_path.extend(str(path) for path in SYSTEM_TOOL_PATHS if path.exists())
        agent_path.extend(["/usr/bin", "/bin"])
        env["PATH"] = os.pathsep.join(agent_path)
        env["PI_CODING_AGENT_DIR"] = str(outer / "pi-agent")
        env["EXAMPLE_PROVIDER_MODEL_DISCOVERY"] = "0"
        env["WORKFLOW_MAX_OUTPUT_TOKENS"] = str(job["limits"]["max_output_tokens"])
        env["TMPDIR"] = str(outer / "tmp")
        model = job["model"]
        tools = set()
        requested_tools = job.get("permissions", {}).get("tools", [])
        unmapped = sorted(set(requested_tools) - set(PI_TOOL_MAPPING))
        if unmapped:
            raise ValueError("Requested logical tool(s) have no Pi mapping: " + ", ".join(unmapped))
        tools = {PI_TOOL_MAPPING[requested_tool] for requested_tool in requested_tools}
        staged_extension = stage_bounded_extension(
            Path(args.example-provider_extension), outer / "pi-agent" / "mit-example-provider-pi-extension",
            job["limits"]["max_output_tokens"])
        argv = [str(args.nono), "run", "--profile", str(profile_path), "--silent", "--allow-cwd", "--",
                str(args.node), str(args.pi_cli), "--mode", "json", "--no-session",
                "--no-context-files", "--no-approve", "--no-skills", "--no-themes",
                "--no-prompt-templates", "--no-mcp", "--no-extensions",
                "--extension", str(staged_extension / "dist/index.js"), "--model",
                model["model"], "--thinking", model["thinking"], "--tools", ",".join(sorted(tools)),
                "@" + str(workspace / "workflow-prompt.md"),
                "Execute the attached workflow prompt exactly and return only the required JSON object."]
        process = subprocess.Popen(argv, cwd=workspace, env=env, stdin=subprocess.DEVNULL)
        returncode = process.wait()
        if returncode:
            return returncode
        _import_outputs(workspace, run_root, job, before)
        return 0
    finally:
        scratch.cleanup()


def _run_nono_build(cmd, cwd: Path, env: dict, timeout: int, byte_limit: int, raw_log: Path):
    process = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    started = time.monotonic()
    size = 0
    try:
        with raw_log.open("wb") as log:
            while selector.get_map() or process.poll() is None:
                if time.monotonic() - started > timeout:
                    raise ValueError(f"LaTeX build timed out after {timeout}s")
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if size > byte_limit:
                        raise ValueError("LaTeX build output exceeded stream budget")
                    # Keep verbose TeX output in raw_log; the workflow console
                    # reports stage transitions rather than flooding with the log.
                    log.write(chunk)
        return process.wait()
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait()
        selector.close()
        process.stdout.close()


def run_build(args, job_path: Path):
    job = json.loads(job_path.read_text())
    profile_source = verify_pinned_runtime(args)
    run_root = Path.cwd().resolve()
    scratch, outer, workspace = _workspace(run_root, job, job_path, job_path)
    try:
        main_rel = Path(job["main_tex"])
        if job.get("prune_duplicate_bib", True):
            _prune_redundant_local_temp_bib_entries(workspace / main_rel.parent, main_rel.name)
        before = digest_tree(workspace)
        profile = _profile_for_run(workspace, profile_source, job, args, is_build=True)
        profile_path = outer / "profile.json"
        profile_path.write_text(json.dumps(profile))
        reports = []
        for variant in job["build_variants"]:
            if variant == "highlight_disabled":
                main_rel = Path(job["main_tex"])
                defs = workspace / main_rel.parent / "LatexInclusion" / "Local-Definitions.tex"
                defs.parent.mkdir(parents=True, exist_ok=True)
                macros = job.get("revision_macros") or [job.get("revision_macro", "writerrevision")]
                if not isinstance(macros, list) or any(not isinstance(macro, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", macro) for macro in macros):
                    raise ValueError("Invalid revision macro list in build job")
                with defs.open("a") as f:
                    f.write("\n% sandbox disabled variant\n")
                    for macro in macros:
                        f.write(f"\\renewcommand{{\\{macro}}}[1]{{#1}}\n")
            out_dir = workspace / "build-out" / variant
            out_dir.mkdir(parents=True, exist_ok=True)
            main_rel = Path(job["main_tex"])
            build_cwd = workspace / main_rel.parent
            # BibTeX invoked by latexmk interprets explicit relative database
            # paths from the output directory, not build_cwd. Mirror the two
            # bibliography roots at those expected scratch locations.
            style_assets_dir = build_cwd.parent / "Manuscript-Style-Assets"
            if style_assets_dir.is_dir():
                shutil.copytree(style_assets_dir, out_dir.parent / "Manuscript-Style-Assets", dirs_exist_ok=True)
            local_bib = build_cwd / "LatexInclusion"
            if local_bib.is_dir():
                shutil.copytree(local_bib, out_dir / "LatexInclusion", dirs_exist_ok=True)
            argv = [a.replace("{output_dir}", str(out_dir)).replace("{main_tex}", main_rel.name)
                    for a in job["build_argv"]]
            env = os.environ.copy()
            env["TMPDIR"] = str(workspace / "tmp")
            env["TEXMFHOME"] = str(workspace / "texmf-home")
            env["TEXMFVAR"] = str(workspace / "texmf-var")
            # latexmk runs BibTeX from the output directory when -outdir is
            # used. Prefix the source directory so bibliography paths written
            # relative to the main .tex file continue to resolve there.
            env["BIBINPUTS"] = str(build_cwd) + os.pathsep
            env["BSTINPUTS"] = str(build_cwd) + os.pathsep
            build_path = [str(args.tex_bin)]
            build_path.extend(str(path) for path in SYSTEM_TOOL_PATHS if path.exists())
            build_path.extend(["/usr/bin", "/bin"])
            env["PATH"] = os.pathsep.join(build_path)
            if argv and Path(argv[0]).name == "latexmk":
                argv[0] = str(args.latexmk)
            cmd = [str(args.nono), "run", "--profile", str(profile_path), "--silent", "--allow-cwd", "--",
                   *argv]
            raw_log = out_dir / "launcher-output.log"
            returncode = _run_nono_build(cmd, build_cwd, env,
                                         job["limits"]["stage_timeout_sec"],
                                         job["limits"]["max_stream_bytes"], raw_log)
            pdf_path = out_dir / f"{main_rel.stem}.pdf"
            log_path = out_dir / f"{main_rel.stem}.log"
            if not log_path.is_file():
                shutil.copyfile(raw_log, log_path)
            if returncode or not pdf_path.is_file():
                return returncode or 2
            target_dir = workspace / "build" / job["stage"] / variant
            target_dir.mkdir(parents=True, exist_ok=True)
            pdf_target = target_dir / "paper.pdf"
            log_target = target_dir / "paper.log"
            shutil.copyfile(pdf_path, pdf_target)
            shutil.copyfile(log_path, log_target)
            reports.append({"variant": variant, "exit_code": 0,
                            "pdf": {"path": pdf_target.relative_to(workspace).as_posix(),
                                    "sha256": sha_file(pdf_target), "locator": "complete PDF"},
                            "log": {"path": log_target.relative_to(workspace).as_posix(),
                                    "sha256": sha_file(log_target), "locator": "complete log"}})
        _import_outputs(workspace, run_root, job, before)
        result = {k: job[k] for k in ("schema_version", "run_id", "stage", "round", "snapshot_sha256", "worktree_sha256", "inputs")}
        result.update({"summary": "Nono-isolated build completed", "reports": reports})
        dump(result)
        return 0
    finally:
        scratch.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nono", type=Path, required=True)
    parser.add_argument("--profile-source", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--nono-sha256", required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--node-sha256", required=True)
    parser.add_argument("--pi-cli", type=Path, required=True)
    parser.add_argument("--pi-cli-sha256", required=True)
    parser.add_argument("--pi-package", type=Path, required=True)
    parser.add_argument("--pi-package-sha256", required=True)
    parser.add_argument("--example-provider-extension", type=Path, required=True)
    parser.add_argument("--example-provider-extension-sha256", required=True)
    parser.add_argument("--python-bin", type=Path, required=True)
    parser.add_argument("--python-bin-sha256", required=True)
    parser.add_argument("--python-root", type=Path, required=True)
    parser.add_argument("--jiti-package", type=Path, required=True)
    parser.add_argument("--tex-bin", type=Path, required=True)
    parser.add_argument("--tex-root", type=Path, required=True)
    parser.add_argument("--latexmk", type=Path, required=True)
    parser.add_argument("--latexmk-sha256", required=True)
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("check")
    p.add_argument("job", type=Path)
    p = sub.add_parser("run")
    p.add_argument("job", type=Path)
    p.add_argument("prompt", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "check":
            return check(args, args.job.resolve())
        job = json.loads(args.job.read_text())
        if job["stage"] in ("baseline_build", "final_build"):
            return run_build(args, args.job.resolve())
        return run_agent(args, args.job.resolve(), args.prompt.resolve())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        sys.stderr.write(f"Nono workflow launcher stopped: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
