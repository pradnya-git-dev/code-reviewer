# code-reviewer

An AI-powered code reviewer that analyzes git diffs and provides detailed feedback.

> **Note:** I am working on this project by using the following repo as a reference: https://github.com/keshawillz/oreilly-claude-pr-review-helper

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- An [Anthropic API key](https://console.anthropic.com/)

## Getting Started

**1. Clone and install dependencies**

```bash
git clone <repo-url>
cd code-reviewer
uv sync
```

**2. Set up your API key**

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:

```
ANTHROPIC_API_KEY=your_api_key_here
```

**3. Run a review**

Pass a diff file as an argument:

```bash
uv run src/review.py path/to/your.diff
```

To review a demo diff:

```bash
uv run src/review.py demos/diffs/day01.diff
```

To review your current git changes:

```bash
git diff > changes.diff
uv run src/review.py changes.diff
```

## Progress Log

| Tag | Changes |
|-----|---------|
| [v0.5.0](https://github.com/pradnya-git-dev/code-reviewer/releases/tag/v0.5.0) | Fake Claude setup for testing without incurreing live API usage charges |
| [v0.4.0](https://github.com/pradnya-git-dev/code-reviewer/releases/tag/v0.4.0) | Improve output quality: Confidence score [0.0, 1.0] for each finding, parse input diff programmatically and validate the AI findings to filter out invalid/hallucinated files/line numbers |
| [v0.3.0](https://github.com/pradnya-git-dev/code-reviewer/releases/tag/v0.3.0) | Enhance the system prompt for the code reviewer: `prompts/system.md` |
| [v0.2.0](https://github.com/pradnya-git-dev/code-reviewer/releases/tag/v0.2.0) | Structured JSON output via `schemas/findings.json`; refactored review logic into `review_diff()`; added `src/helpers.py` with `ROOT` and `first_text` utilities |
| [v0.1.0](https://github.com/pradnya-git-dev/code-reviewer/releases/tag/v0.1.0) | Basic diff review via Claude API; plain-text response printed to stdout; `uv` project setup with `.env` config and demo diff |
