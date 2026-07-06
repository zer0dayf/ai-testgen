<div align="center">

# AI Test Review

**A portable GitHub Action that writes and reviews your tests with AI — in any language.**

Add it to any repo with a tiny workflow and one API key. It writes tests for
changed code, or **bootstraps a whole test suite from scratch** if the repo has
none, then tells real source bugs apart from broken generated tests.

</div>

---

## What it does

- **`diff` mode** — on every push/PR, generates tests only for the functions you
  changed.
- **`full` (bootstrap) mode** — if the repo has **no tests at all**, it scaffolds
  the test directory and writes a test file for each source file, from scratch.
- **`auto` mode** (default) — bootstraps when there are no tests, otherwise diffs.
- **Language-agnostic review** — on a failing run, the whole test output goes to
  an AI classifier that decides *broken test* vs *real source bug*. Broken tests
  are regenerated and retried, then discarded if unfixable (CI stays green). A
  real bug writes `bug_report.md`, comments on the PR / opens an issue, and fails
  the check. There is **no per-language output parsing** — adding a language is a
  config preset, not code.

## Quick start (add to any repo)

1. Create `.github/workflows/ai-test-review.yml`:

```yaml
name: AI Test Review
on:
  push: { branches: [main, master] }
  pull_request:
permissions: { contents: read, pull-requests: write, issues: write }
jobs:
  ai-test-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: zer0dayf/ai-testgen@v1
        with:
          mode: auto
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

2. Add one provider key as a repo secret: `ANTHROPIC_API_KEY`,
   `DEEPSEEK_API_KEY`, or `OPENAI_API_KEY`.

That's it. Without a key the action **skips** (green), so forks are safe.

## Configure

Drop an optional `.aitestgen.toml` at your repo root (see
`examples/aitestgen.toml.example`). Start from a preset and override what differs:

```toml
language      = "python"           # python | javascript | go | rust
source_glob   = "src/**/*.py"
test_dir      = "tests/generated"  # diff mode (ephemeral)
bootstrap_dir = "tests"            # full mode (the real suite)
run_cmd       = ["{py}", "-m", "pytest", "{test_path}", "-q"]
install       = "pip install -r requirements.txt pytest"
```

Every field is also settable via action `with:` inputs or `AITG_*` env vars.

### Action inputs

| Input | Default | Notes |
|---|---|---|
| `mode` | `auto` | `auto` \| `diff` \| `full` |
| `provider` | auto | `anthropic` \| `deepseek` \| `openai` |
| `model` | provider default | e.g. `claude-sonnet-4-6` |
| `*-api-key` | — | pass the matching secret |
| `config-path` | auto | path to `.aitestgen.toml/.json` |
| `language` | auto | preset override |
| `source-glob` | from config | pathspec glob |
| `install` | from config | deps install command |
| `python-version` | `3.11` | runs the orchestrator |

## Run it locally (no GitHub needed)

The engine is a plain CLI — works in any CI or on your machine:

```bash
ANTHROPIC_API_KEY=sk-... python ai_testgen.py --mode auto --base-ref HEAD~1 --head-ref HEAD
python ai_testgen.py --print-config    # show resolved config
python ai_testgen.py --mode full --dry-run   # list what bootstrap would create
```

## Adding a language

Built-in presets: `python`, `javascript`, `go`, `rust`.

Add a block to `PRESETS` in `ai_testgen.py`, or just set the fields in
`.aitestgen.toml`. A preset needs `language`, `framework`, `source_glob`,
`test_dir`, `bootstrap_dir`, `test_globs`, `test_name`, `code_fence`,
`comment_prefix`, `run_cmd`, `install`, and `detect_files`; optional
`extra_rules` appends a language-specific instruction to the prompt. `run_cmd`
placeholders: `{py}`, `{test_path}`, `{test_dir}`, `{stem}` (test file name
without extension — e.g. `cargo test --test {stem}`). For non-Python targets,
add the toolchain setup (`actions/setup-node`, `actions/setup-go`, …) via the
`install` input or a step before the action.

**Compiled languages (Go, Rust):** tests are compiled against the crate/package,
so generated files can only exercise the **public** API. In Rust, `cargo` runs
integration tests from the top-level `tests/` dir, so both modes write there and
each generated target is run with `cargo test --test {stem}`. Because that dir
overlaps real integration tests, on a Rust repo that already has tests you may
want to set `mode: diff` explicitly rather than relying on `auto`.

## License

MIT © Efe Gungor
