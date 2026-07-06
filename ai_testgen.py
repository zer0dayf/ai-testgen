#!/usr/bin/env python3
"""
ai_testgen — portable, language-agnostic AI test generation & review
====================================================================
A single-file engine you can run anywhere (locally or in any CI) or consume as
a GitHub Action. It has two modes:

  diff  — write tests only for functions changed in a git diff (day-to-day).
  full  — bootstrap a whole test suite from scratch for a repo that has none
          (creates the test directory structure + tests for each source file).
  auto  — pick `full` when the repo has no tests yet, otherwise `diff`.

On a failing run the entire runner output goes to an AI classifier that decides
"broken test" vs "real source bug" — so nothing here is tied to one language's
test-output format. Broken tests are regenerated/retried then discarded if
unfixable (CI stays green); a real source bug writes bug_report.md and exits 1.

Config resolution (later wins):
    language preset  <  .aitestgen.toml/.json  <  AITG_* env vars  <  CLI flags

Providers (auto-detected from whichever key is set, or AI_PROVIDER):
    anthropic -> ANTHROPIC_API_KEY   deepseek -> DEEPSEEK_API_KEY   openai -> OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# ── Repo root: the repo being TESTED (consumer workspace), not this script ────

def _resolve_root() -> Path:
    for cand in (os.environ.get("GITHUB_WORKSPACE"), os.environ.get("AITG_PROJECT_ROOT")):
        if cand and Path(cand).exists():
            return Path(cand).resolve()
    cur = Path.cwd().resolve()
    for parent in (cur, *cur.parents):
        if (parent / ".git").exists():
            return parent
    return cur


PROJECT_ROOT   = _resolve_root()
MAX_RETRIES    = int(os.environ.get("AITG_MAX_RETRIES", "2"))
MAX_DIFF_CHARS = int(os.environ.get("AITG_MAX_DIFF_CHARS", "12000"))
MAX_SRC_CHARS  = int(os.environ.get("AITG_MAX_SRC_CHARS", "8000"))
MAX_FULL_FILES = int(os.environ.get("AITG_MAX_FULL_FILES", "12"))


# ── Language presets (everything is overridable via config/env) ───────────────

PRESETS: dict[str, dict] = {
    "python": {
        "language":     "Python",
        "framework":    "pytest",
        "source_glob":  "**/*.py",
        "test_dir":     "tests/generated",
        "bootstrap_dir":"tests",
        "test_globs":   ["test_*.py", "*_test.py"],
        "test_name":    "test_{stem}.py",
        "test_ext":     ".py",
        "code_fence":   "python",
        "comment_prefix": "#",
        "mock_libs":    "unittest.mock (mock out sockets, network I/O, filesystem, subprocess)",
        "run_cmd":      ["{py}", "-m", "pytest", "{test_path}", "-q", "--tb=short", "--no-header"],
        "install":      "pip install -r requirements.txt pytest || pip install pytest",
        "detect_files": ["pyproject.toml", "setup.py", "requirements.txt"],
    },
    "javascript": {
        "language":     "JavaScript/TypeScript",
        "framework":    "Jest",
        "source_glob":  "src/**/*.{js,ts,jsx,tsx}",
        "test_dir":     "__tests__/generated",
        "bootstrap_dir":"__tests__",
        "test_globs":   ["*.test.js", "*.spec.js", "*.test.ts", "*.spec.ts"],
        "test_name":    "{stem}.test.js",
        "test_ext":     ".test.js",
        "code_fence":   "javascript",
        "comment_prefix": "//",
        "mock_libs":    "jest.mock (mock out network, timers, fs)",
        "run_cmd":      ["npx", "jest", "{test_path}", "--silent"],
        "install":      "npm ci || npm install",
        "detect_files": ["package.json"],
    },
    "go": {
        "language":     "Go",
        "framework":    "the standard testing package",
        "source_glob":  "**/*.go",
        "test_dir":     "aigen",
        "bootstrap_dir":".",
        "test_globs":   ["*_test.go"],
        "test_name":    "{stem}_ai_test.go",
        "test_ext":     "_ai_test.go",
        "code_fence":   "go",
        "comment_prefix": "//",
        "mock_libs":    "interfaces / net/http/httptest (avoid real network)",
        "run_cmd":      ["go", "test", "./..."],
        "install":      "go mod download",
        "detect_files": ["go.mod"],
    },
}


# ── AI providers ──────────────────────────────────────────────────────────────

_PROVIDERS = {
    "anthropic": {"env_key": "ANTHROPIC_API_KEY", "default_model": "claude-sonnet-4-6"},
    "deepseek":  {"env_key": "DEEPSEEK_API_KEY",  "default_model": "deepseek-chat",
                  "base_url": "https://api.deepseek.com"},
    "openai":    {"env_key": "OPENAI_API_KEY",    "default_model": "gpt-4o"},
}


def detect_provider() -> str:
    explicit = os.environ.get("AI_PROVIDER", "").lower()
    if explicit in _PROVIDERS:
        return explicit
    for name, cfg in _PROVIDERS.items():
        if os.environ.get(cfg["env_key"]):
            return name
    return "anthropic"


def have_key() -> bool:
    return bool(os.environ.get(_PROVIDERS[detect_provider()]["env_key"]))


# ── Config ────────────────────────────────────────────────────────────────────

def _read_config_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import tomllib
        return tomllib.loads(text)
    except ModuleNotFoundError:
        try:
            import tomli
            return tomli.loads(text)
        except ModuleNotFoundError:
            print("⚠️  TOML needs Python 3.11+ or `pip install tomli`; use .aitestgen.json.")
            return {}


def _autodetect_language() -> str:
    for lang, preset in PRESETS.items():
        if any((PROJECT_ROOT / f).exists() for f in preset.get("detect_files", [])):
            return lang
    return "python"


_ENV_OVERRIDES = {
    "AITG_LANGUAGE": "language", "AITG_FRAMEWORK": "framework",
    "AITG_SOURCE_GLOB": "source_glob", "AITG_TEST_DIR": "test_dir",
    "AITG_BOOTSTRAP_DIR": "bootstrap_dir", "AITG_TEST_EXT": "test_ext",
    "AITG_CODE_FENCE": "code_fence", "AITG_MOCK_LIBS": "mock_libs",
    "AITG_INSTALL": "install", "AITG_PROJECT": "project", "AITG_RUN_CMD": "run_cmd",
}


def load_config(cli_config: str | None) -> dict:
    candidates = [Path(cli_config)] if cli_config else [
        PROJECT_ROOT / ".aitestgen.toml", PROJECT_ROOT / ".aitestgen.json",
    ]
    file_cfg: dict = {}
    for c in candidates:
        if c.exists():
            file_cfg = _read_config_file(c)
            break

    lang_key = (
        os.environ.get("AITG_LANGUAGE")
        or file_cfg.get("language_preset") or file_cfg.get("preset")
        or (str(file_cfg.get("language", "")).lower())
        or _autodetect_language()
    ).lower()
    alias = {"js": "javascript", "ts": "javascript", "typescript": "javascript",
             "py": "python", "golang": "go"}
    lang_key = alias.get(lang_key, lang_key)
    cfg = dict(PRESETS.get(lang_key, PRESETS["python"]))

    cfg.update({k: v for k, v in file_cfg.items() if v is not None})
    for env, key in _ENV_OVERRIDES.items():
        val = os.environ.get(env)
        if not val:
            continue
        if key == "run_cmd":
            try:
                cfg[key] = json.loads(val)
            except json.JSONDecodeError:
                cfg[key] = val.split()
        else:
            cfg[key] = val

    cfg.setdefault("project", PROJECT_ROOT.name)
    cfg.setdefault("comment_prefix", "#")
    cfg.setdefault("bootstrap_dir", "tests")
    cfg.setdefault("test_globs", ["test_*.py", "*_test.py"])
    cfg.setdefault("test_name", "test_{stem}" + cfg.get("test_ext", ".py"))
    return cfg


# ── Git / source discovery ────────────────────────────────────────────────────

def _git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=PROJECT_ROOT,
                                   stderr=subprocess.DEVNULL, text=True)


def get_diff(base_ref: str, head_ref: str, source_glob: str) -> tuple[str, list[Path]]:
    spec = f":(glob){source_glob}"
    try:
        raw = _git(["diff", base_ref, head_ref, "--", spec])
        changed = _git(["diff", "--name-only", base_ref, head_ref, "--", spec]).split()
    except subprocess.CalledProcessError:
        return "", []
    files = [PROJECT_ROOT / f for f in changed if (PROJECT_ROOT / f).exists()]
    return raw[:MAX_DIFF_CHARS], files


def list_source_files(source_glob: str) -> list[Path]:
    try:
        out = _git(["ls-files", "--", f":(glob){source_glob}"])
        files = [PROJECT_ROOT / f for f in out.split() if (PROJECT_ROOT / f).exists()]
        if files:
            return sorted(files)
    except subprocess.CalledProcessError:
        pass
    return sorted(PROJECT_ROOT.glob(source_glob))


def _is_test_file(path: Path, cfg: dict) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(path.name, g) for g in cfg["test_globs"])


def has_existing_tests(cfg: dict) -> bool:
    """True if the repo already has hand-written tests (outside the generated dir)."""
    gen_dir = (PROJECT_ROOT / cfg["test_dir"]).resolve()
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or not _is_test_file(path, cfg):
            continue
        if gen_dir in path.resolve().parents or gen_dir == path.resolve().parent:
            continue
        if skip & set(p.name for p in path.parents):
            continue
        return True
    return False


def read_source(paths: list[Path]) -> str:
    parts = []
    for p in paths:
        try:
            parts.append(f"# === {p.name} ===\n{p.read_text(encoding='utf-8')[:MAX_SRC_CHARS]}")
        except OSError:
            pass
    return "\n\n".join(parts)


def read_existing_tests(cfg: dict) -> str:
    parts = []
    gen_dir = (PROJECT_ROOT / cfg["test_dir"]).resolve()
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file() or not _is_test_file(path, cfg):
            continue
        if gen_dir in path.resolve().parents:
            continue
        try:
            parts.append(f"# === {path.name} ===\n{path.read_text(encoding='utf-8')[:4000]}")
        except OSError:
            pass
        if len(parts) >= 8:
            break
    return "\n\n".join(parts)


# ── AI calls ──────────────────────────────────────────────────────────────────

def call_ai(system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096) -> str:
    provider = detect_provider()
    cfg      = _PROVIDERS[provider]
    api_key  = os.environ.get(cfg["env_key"])
    if not api_key:
        raise RuntimeError(f"Missing API key env var '{cfg['env_key']}'.")
    model = os.environ.get("AI_MODEL") or cfg["default_model"]

    if provider == "anthropic":
        try:
            import anthropic
        except ImportError:
            print("❌ pip install anthropic"); sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(model=model, max_tokens=max_tokens,
                                      temperature=temperature, system=system,
                                      messages=[{"role": "user", "content": user}])
        return msg.content[0].text

    try:
        from openai import OpenAI
    except ImportError:
        print("❌ pip install openai"); sys.exit(1)
    kw = {"api_key": api_key}
    if "base_url" in cfg:
        kw["base_url"] = cfg["base_url"]
    client = OpenAI(**kw)
    resp = client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return resp.choices[0].message.content


def extract_code_block(text: str, fence: str) -> str:
    for opener in (f"```{fence}", "```"):
        if opener in text:
            start = text.index(opener) + len(opener)
            end   = text.find("```", start)
            return text[start:end if end != -1 else None].strip()
    return text.strip()


# ── Prompts ───────────────────────────────────────────────────────────────────

def _rules(cfg: dict) -> str:
    return textwrap.dedent(f"""
        - Write only unit tests that need no network or external services;
          mock them out using {cfg['mock_libs']}.
        - Each test must run independently.
        - Cover success, failure, and edge-case paths.
        - Include all necessary imports at the top.
        - Return ONLY valid {cfg['language']} code inside a ```{cfg['code_fence']}
          ... ``` block — no prose.
    """).strip()


def generate_diff_tests(cfg: dict, diff: str, source: str, existing: str) -> str:
    system = (f"You are an expert {cfg['language']} test engineer using "
              f"{cfg['framework']} for the project \"{cfg['project']}\".\n\nRULES:\n"
              f"{_rules(cfg)}\n- Test ONLY the changed/added functions in the diff.\n"
              f"- Do NOT duplicate the existing tests; complement them.")
    user = textwrap.dedent(f"""
        Write {cfg['framework']} tests for the changed/added functions.

        ## GIT DIFF
        ```diff
        {diff}
        ```
        ## CHANGED SOURCE
        ```{cfg['code_fence']}
        {source}
        ```
        ## EXISTING TESTS (do not repeat)
        ```{cfg['code_fence']}
        {existing[:6000]}
        ```
        Return the new tests in one ```{cfg['code_fence']} ... ``` block.
    """).strip()
    return call_ai(system, user, max_tokens=8192)


def generate_full_tests(cfg: dict, filename: str, code: str) -> str:
    system = (f"You are an expert {cfg['language']} test engineer using "
              f"{cfg['framework']} for the project \"{cfg['project']}\". This repo has "
              f"NO tests yet — you are creating its test suite from scratch.\n\nRULES:\n"
              f"{_rules(cfg)}\n- Write a complete, self-contained test file for the "
              f"public functions/classes in the given source file.")
    user = textwrap.dedent(f"""
        Create a {cfg['framework']} test file for this source file.

        ## SOURCE FILE: {filename}
        ```{cfg['code_fence']}
        {code}
        ```
        Return the whole test file in one ```{cfg['code_fence']} ... ``` block.
    """).strip()
    return call_ai(system, user, max_tokens=8192)


_CLASSIFY_SYSTEM = textwrap.dedent("""
    You are a senior test engineer reviewing a FAILED test run. Decide the cause:
      A) TEST_BUG   — the test is wrong: bad syntax, won't compile/collect, wrong
                      mock target, unrealistic assertion, wrong import. Source is fine.
      B) SOURCE_BUG — the test is reasonable and exposed a real bug in the source.
    Respond with ONLY this JSON:
    {"classification":"test_bug"|"source_bug","confidence":0.0-1.0,
     "reason":"one sentence","bug_description":"if source_bug: what & how to fix; else ''"}
""").strip()


def classify_failure(cfg: dict, source: str, test_code: str, output: str) -> dict:
    user = (f"## SOURCE\n```{cfg['code_fence']}\n{source[:6000]}\n```\n"
            f"## GENERATED TEST\n```{cfg['code_fence']}\n{test_code[:6000]}\n```\n"
            f"## RUNNER OUTPUT\n```\n{output[-4000:]}\n```")
    raw = call_ai(_CLASSIFY_SYSTEM, user, temperature=0.0, max_tokens=1024)
    try:
        return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"classification": "test_bug", "confidence": 0.0,
                "reason": "unparseable classifier response", "bug_description": ""}


_FIX_SYSTEM = textwrap.dedent("""
    The generated test file below failed for a TEST-side reason (bad syntax,
    won't compile/collect, wrong mock, unrealistic assertion) — NOT a real source
    bug. Rewrite the WHOLE file so it is valid and runnable, preserving intent.
    Return ONLY a complete, self-contained file inside a code block — no prose.
""").strip()


def fix_test_file(cfg: dict, test_code: str, output: str, source: str) -> str:
    user = (f"## BROKEN TEST (whole)\n```{cfg['code_fence']}\n{test_code}\n```\n"
            f"## ERROR\n```\n{output[-3000:]}\n```\n"
            f"## SOURCE (reference)\n```{cfg['code_fence']}\n{source[:6000]}\n```\n"
            f"Return the fixed WHOLE file in a ```{cfg['code_fence']} ... ``` block.")
    return call_ai(_FIX_SYSTEM, user, max_tokens=8192)


# ── Test runner + review loop ─────────────────────────────────────────────────

def run_tests(cfg: dict, test_file: Path) -> tuple[int, str]:
    cmd = [p.replace("{py}", sys.executable).replace("{test_path}", str(test_file))
            .replace("{test_dir}", str(test_file.parent)) for p in cfg["run_cmd"]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    except FileNotFoundError as e:
        return 127, f"Test runner not found: {e}"
    return r.returncode, r.stdout + r.stderr


def review_loop(cfg: dict, test_file: Path, test_code: str, source: str, header: str) -> tuple[str, dict]:
    """
    Run a generated test file; return (status, analysis).
      status = "passed" | "discarded" | "source_bug"
    Broken tests are regenerated up to MAX_RETRIES then discarded.
    """
    exit_code, output = run_tests(cfg, test_file)
    print(output)
    attempts = 0
    while exit_code != 0:
        analysis = classify_failure(cfg, source, test_code, output)
        cls = analysis.get("classification", "test_bug")
        print(f"🔎 {test_file.name}: {cls} ({analysis.get('confidence', 0):.0%}) — {analysis.get('reason','')}")
        if cls == "source_bug":
            return "source_bug", {**analysis, "output": output}
        if attempts >= MAX_RETRIES:
            print(f"⚠️  {test_file.name}: still broken after {MAX_RETRIES} fixes — discarding.")
            test_file.unlink(missing_ok=True)
            return "discarded", {}
        attempts += 1
        print(f"🔧 Fixing {test_file.name} (attempt {attempts}/{MAX_RETRIES})...")
        fixed = extract_code_block(fix_test_file(cfg, test_code, output, source), cfg["code_fence"])
        if not fixed:
            test_file.unlink(missing_ok=True)
            return "discarded", {}
        test_code = fixed
        test_file.write_text(header + "\n" + test_code, encoding="utf-8")
        exit_code, output = run_tests(cfg, test_file)
        print(output)
    print(f"✅ {test_file.name}: passed.")
    return "passed", {}


def write_bug_report(cfg: dict, items: list[dict]) -> Path:
    report = PROJECT_ROOT / "bug_report.md"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"## 🐛 {cfg['project']} — AI Test Review Bug Report", "",
             f"**Date:** {ts}  ", f"**Bugs:** {len(items)}", "", "---", ""]
    for i, it in enumerate(items, 1):
        a = it["analysis"]
        lines += [f"### Bug #{i}: `{it['test_file']}`", "",
                  f"**Confidence:** {a.get('confidence', 0):.0%}", "",
                  "**Description:**  ", a.get("bug_description", "—"), "",
                  "**Runner output:**", "```",
                  "\n".join(a.get("output", "").splitlines()[-25:]), "```", "", "---", ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def _header(cfg: dict, base: str, head: str) -> str:
    c = cfg.get("comment_prefix", "#")
    return (f"{c} AI-generated {datetime.now():%Y-%m-%d %H:%M} — {base}..{head} — "
            "review before committing\n")


def _test_filename(cfg: dict, stem: str) -> str:
    return cfg["test_name"].replace("{stem}", stem)


# ── Modes ─────────────────────────────────────────────────────────────────────

def run_diff_mode(cfg: dict, base: str, head: str, dry: bool) -> int:
    diff, changed = get_diff(base, head, cfg["source_glob"])
    if not diff.strip():
        print("ℹ️  No changes under the source glob — skipping.")
        return 0
    print(f"   Changed: {[f.name for f in changed]}")
    if dry:
        print(f"🔵 --dry-run: would generate tests into {cfg['test_dir']}/")
        return 0

    source   = read_source(changed)
    existing = read_existing_tests(cfg)
    test_code = extract_code_block(generate_diff_tests(cfg, diff, source, existing), cfg["code_fence"])
    if not test_code:
        print("⚠️  No test code produced — skipping.")
        return 0

    test_dir = PROJECT_ROOT / cfg["test_dir"]
    test_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = cfg["test_ext"]
    name = f"test_ai_{ts}{ext if ext.startswith(('.', '_')) else '.' + ext}"
    test_file = test_dir / name
    header = _header(cfg, base, head)
    test_file.write_text(header + "\n" + test_code, encoding="utf-8")
    print(f"✅ Wrote {test_file.relative_to(PROJECT_ROOT)}\n🧪 Running...")

    status, analysis = review_loop(cfg, test_file, test_code, source, header)
    if status == "source_bug":
        report = write_bug_report(cfg, [{"test_file": test_file.name, "analysis": analysis}])
        print(f"🐛 Real source bug. Wrote {report.name}")
        return 1
    return 0


def run_full_mode(cfg: dict, base: str, head: str, dry: bool) -> int:
    files = list_source_files(cfg["source_glob"])
    if not files:
        print("ℹ️  No source files under the glob — nothing to bootstrap.")
        return 0
    if len(files) > MAX_FULL_FILES:
        print(f"   {len(files)} files — capping at {MAX_FULL_FILES} (AITG_MAX_FULL_FILES).")
        files = files[:MAX_FULL_FILES]

    boot_dir = PROJECT_ROOT / cfg["bootstrap_dir"]
    print(f"🌱 Bootstrapping test suite into {cfg['bootstrap_dir']}/ for {len(files)} file(s).")
    if dry:
        for src in files:
            print(f"   would write {cfg['bootstrap_dir']}/{_test_filename(cfg, src.stem)}  ← {src.name}")
        return 0

    boot_dir.mkdir(parents=True, exist_ok=True)
    header = _header(cfg, base, head)
    kept, bugs = 0, []
    for src in files:
        try:
            code = src.read_text(encoding="utf-8")[:MAX_SRC_CHARS]
        except OSError:
            continue
        print(f"\n── {src.name} ──")
        test_code = extract_code_block(generate_full_tests(cfg, src.name, code), cfg["code_fence"])
        if not test_code:
            print(f"⚠️  {src.name}: no tests produced — skipping.")
            continue
        test_file = boot_dir / _test_filename(cfg, src.stem)
        test_file.write_text(header + "\n" + test_code, encoding="utf-8")
        status, analysis = review_loop(cfg, test_file, test_code, code, header)
        if status == "passed":
            kept += 1
        elif status == "source_bug":
            bugs.append({"test_file": test_file.name, "analysis": analysis})
            # keep the test file: it documents the bug

    print(f"\n🌱 Bootstrap done: {kept} test file(s) kept in {cfg['bootstrap_dir']}/, "
          f"{len(bugs)} suspected source bug(s).")
    if bugs:
        report = write_bug_report(cfg, bugs)
        print(f"🐛 Wrote {report.name}")
        return 1
    return 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Portable AI test generation & review")
    ap.add_argument("--mode", choices=["auto", "diff", "full"], default=os.environ.get("AITG_MODE", "auto"))
    ap.add_argument("--base-ref", default="HEAD~1")
    ap.add_argument("--head-ref", default="HEAD")
    ap.add_argument("--config", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print-config", action="store_true")
    ap.add_argument("--print-install", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.print_install:
        print(cfg.get("install", "")); return 0
    if args.print_config:
        print(json.dumps(cfg, indent=2, default=str)); return 0

    # Resolve auto → diff/full
    mode = args.mode
    if mode == "auto":
        mode = "diff" if has_existing_tests(cfg) else "full"

    print(f"📦 {cfg['project']} | {cfg['language']} / {cfg['framework']} | "
          f"mode={mode} | glob={cfg['source_glob']}")

    if args.dry_run:
        return run_full_mode(cfg, args.base_ref, args.head_ref, True) if mode == "full" \
            else run_diff_mode(cfg, args.base_ref, args.head_ref, True)

    if not have_key():
        keys = " | ".join(c["env_key"] for c in _PROVIDERS.values())
        print(f"ℹ️  No AI API key found ({keys}) — skipping AI test review.")
        return 0
    print(f"🤖 Provider: {detect_provider()} | "
          f"Model: {os.environ.get('AI_MODEL') or _PROVIDERS[detect_provider()]['default_model']}")

    if mode == "full":
        return run_full_mode(cfg, args.base_ref, args.head_ref, False)
    return run_diff_mode(cfg, args.base_ref, args.head_ref, False)


if __name__ == "__main__":
    sys.exit(main())
