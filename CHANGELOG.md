# Changelog

## v1.0.0 — 2026-07-06

Initial release.

- Composite GitHub Action: `uses: zer0dayf/ai-testgen@v1`.
- `diff` mode — generate tests for functions changed in a git diff.
- `full` / bootstrap mode — scaffold a whole test suite from scratch for a repo
  that has no tests (creates the test directory + a test file per source file).
- `auto` mode (default) — bootstrap when there are no tests, else diff.
- Language-agnostic review: an AI classifier decides broken-test vs real
  source-bug from the raw runner output. Broken tests are regenerated/retried
  then discarded (CI stays green); a real bug writes `bug_report.md`, comments on
  the PR / opens an issue, and fails the check.
- Config via `.aitestgen.toml` / `.aitestgen.json`, `AITG_*` env vars, or action
  inputs. Built-in presets for Python, JavaScript/TypeScript, and Go.
- Providers auto-detected: Anthropic, DeepSeek, OpenAI. Missing key → skip
  (exit 0), so forks and unconfigured repos stay green.
