<div align="center">

# AI Test Review

**English** | **[Türkçe](README.tr.md)**

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

Built-in language presets: **Python** (pytest), **JavaScript/TypeScript** (Jest),
**Go**, **Rust**. The language is auto-detected from your repo
(`pyproject.toml` / `package.json` / `go.mod` / `Cargo.toml`).

## Installation (step by step)

You need two things: **a workflow file** and **one API key stored as a repo
secret**. That's the whole integration — no app to install, nothing to add to
your codebase.

### Step 1 — Create the workflow file

In the repo you want tested, create this file at exactly this path:

```
.github/workflows/ai-test-review.yml
```

with this content:

```yaml
name: AI Test Review

on:
  push:
    branches: [main, master]
  pull_request:
  workflow_dispatch:        # lets you also trigger it manually from the Actions tab

permissions:
  contents: read
  pull-requests: write      # needed to comment the bug report on PRs
  issues: write             # needed to open an issue on push

jobs:
  ai-test-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0    # IMPORTANT: full history, so git diffs resolve

      - uses: zer0dayf/ai-testgen@v1
        with:
          mode: auto
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Two lines people most often miss:

- **`fetch-depth: 0`** on the checkout step — without it, `diff` mode has no
  history to diff against and will find no changes.
- **The `permissions:` block** — without it, the action still generates and runs
  tests, but can't comment on PRs or open issues when it finds a bug.

> Using DeepSeek or OpenAI instead? Replace the last line with
> `deepseek-api-key: ${{ secrets.DEEPSEEK_API_KEY }}` or
> `openai-api-key: ${{ secrets.OPENAI_API_KEY }}`. You only need **one** provider.

### Step 2 — Get an API key

Any one of these works:

| Provider | Get a key at | Default model |
|---|---|---|
| Anthropic | https://console.anthropic.com → API Keys | `claude-sonnet-4-6` |
| DeepSeek | https://platform.deepseek.com → API Keys | `deepseek-chat` |
| OpenAI | https://platform.openai.com → API Keys | `gpt-4o` |

### Step 3 — Add the key as a repository secret

In your repo on GitHub:

1. Go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name it **exactly** `ANTHROPIC_API_KEY` (or `DEEPSEEK_API_KEY` /
   `OPENAI_API_KEY` — it must match the name used in your workflow file).
4. Paste the key as the value and save.

If the secret is missing or empty, the action **skips with a green check**
instead of failing — so forks and PRs from outside contributors are safe.

### Step 4 — Push and watch the first run

Commit and push the workflow file (or open a PR). Then open the **Actions** tab
and click the "AI Test Review" run. On the first run:

- If your repo **has no tests yet**, `auto` picks **full/bootstrap** mode: it
  creates the test directory (e.g. `tests/` for Python) and writes one test
  file per source file, runs each one, and keeps the ones that pass.
- If your repo **already has tests**, `auto` picks **diff** mode: it generates
  tests only for the code changed in that push/PR, into an ephemeral dir
  (e.g. `tests/generated/`).

### Step 5 — Where to find the results

- **Generated test files** are uploaded as a workflow artifact named
  `ai-generated-tests` (run page → *Artifacts*, kept 14 days). The action does
  **not** commit anything to your repo — download the artifact, review the
  tests, and commit the ones you want to keep.
- **If a real source bug is found:** the job fails ❌, a `bug_report.md` is
  produced, and — on a PR — it's posted as a **PR comment**; on a push, a
  **GitHub issue** is opened (labels: `bug`, `ai-detected`).
- **If a generated test was just broken:** it's auto-fixed and retried up to
  2 times, then discarded. Your CI stays green — you'll never be blocked by a
  bad generated test.

### Non-Python projects: one extra step

The action itself runs on Python (the orchestrator), but your project's own
toolchain must be available to *run* the generated tests. `ubuntu-latest`
already ships Node, Go, and Rust, but your project's **dependencies** still
need installing. Either rely on the preset's default install command
(`npm ci`, `go mod download`, `cargo build --tests`, …) or set it explicitly:

```yaml
      - uses: zer0dayf/ai-testgen@v1
        with:
          mode: auto
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          install: "npm ci && npm install --save-dev jest"
```

You can also add your usual setup steps (`actions/setup-node`,
`actions/setup-go`, …) *before* the action — it runs in the same job.

## Configuration (all optional)

Zero config works for standard layouts. To customize, drop a `.aitestgen.toml`
at your repo root (full example in `examples/aitestgen.toml.example`). Start
from a preset and override only what differs:

```toml
language      = "python"           # python | javascript | go | rust
source_glob   = "src/**/*.py"      # which files to watch/test
test_dir      = "tests/generated"  # diff mode writes here (ephemeral)
bootstrap_dir = "tests"            # full mode writes here (the real suite)
run_cmd       = ["{py}", "-m", "pytest", "{test_path}", "-q"]
install       = "pip install -r requirements.txt pytest"
```

Every field is also settable via action `with:` inputs or `AITG_*` env vars.
Precedence (later wins): **preset < config file < env vars < action inputs/CLI flags**.

### Action inputs

| Input | Default | Notes |
|---|---|---|
| `mode` | `auto` | `auto` \| `diff` \| `full` |
| `provider` | auto-detected | `anthropic` \| `deepseek` \| `openai` |
| `model` | provider default | e.g. `claude-sonnet-4-6` |
| `anthropic-api-key` / `deepseek-api-key` / `openai-api-key` | — | pass the matching secret; one is enough |
| `config-path` | auto-discovered | path to `.aitestgen.toml/.json` |
| `language` | auto-detected | preset override: `python` \| `javascript` \| `go` \| `rust` |
| `source-glob` | from preset/config | git pathspec glob of files to watch |
| `install` | from preset/config | shell command to install your project's test deps |
| `python-version` | `3.11` | Python used to run the orchestrator only |

## Run it locally (no GitHub needed)

The engine is a plain, single-file CLI — works in any CI or on your machine:

```bash
pip install -r requirements.txt                 # AI SDKs (+ tomli on Python < 3.11)
eval "$(python ai_testgen.py --print-install)"  # YOUR project's test deps (pytest / npm ci / …)

# generate + review tests for your last commit:
ANTHROPIC_API_KEY=sk-... python ai_testgen.py --mode auto --base-ref HEAD~1 --head-ref HEAD

# useful checks that need no API key:
python ai_testgen.py --print-config          # show the resolved config
python ai_testgen.py --mode full --dry-run   # list what bootstrap would create
```

The `--print-install` line installs the test dependencies of the project being
tested — `pytest` for Python, `npm ci` for JavaScript, and so on, resolved from
the detected language preset (or your `.aitestgen.toml`). It's the exact same
command the action runs in CI, so local and CI behave the same.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "No changes under the source glob — skipping" | Checkout is shallow — add `fetch-depth: 0`; or your files don't match `source_glob` (check with `--print-config`). |
| "No AI API key found — skipping" | The secret name in the workflow doesn't match the one you created, or the secret isn't set in *this* repo (forks don't inherit secrets — that's by design). |
| Bug found but no PR comment / issue appears | Add the `permissions:` block from Step 1 to your workflow. |
| Tests fail with "runner not found" (127) | The test toolchain isn't installed — set the `install` input or add a `setup-*` step before the action. |
| Wrong language detected | Set `language:` explicitly in the workflow or in `.aitestgen.toml`. |

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
