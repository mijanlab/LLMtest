<div align="center">

# `llmtest`

**Ultra-fast, zero-dependency streaming latency & throughput benchmark for OpenAI-compatible LLM endpoints.**

[![PyPI Version](https://img.shields.io/badge/pypi-v1.0.3-09090b?style=flat-square&logo=pypi&logoColor=white&labelColor=27272a)](https://github.com/mijanlab/LLMtest)
[![Python Version](https://img.shields.io/badge/python-3.10+-09090b?style=flat-square&logo=python&logoColor=white&labelColor=27272a)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-09090b?style=flat-square&labelColor=27272a)](https://github.com/mijanlab/LLMtest)
[![License](https://img.shields.io/badge/license-MIT-09090b?style=flat-square&labelColor=27272a)](LICENSE)

<br />

[Quickstart](#quickstart) • [One-Line Run](#one-line-run-no-install) • [CLI Usage](#cli-usage) • [Interactive Web Report](#interactive-web-report) • [Metrics](#metrics-measured) • [Security](#security)

</div>

<br />

```text
  ⚡ LLM Speed & Latency Benchmark (v1.0.3)
  ═══════════════════════════════════════════════════════════════════════════════════
  Endpoint : https://api.openai.com/v1
  Models   : 8 discovered | Concurrency: 1 | Prompt: 4 tokens ("Say hello in 5 words")
  ═══════════════════════════════════════════════════════════════════════════════════

  #  │ Model ID                  │ Status    │ TTFT     │ Total Time │ Throughput │ Output Preview
  ───┼───────────────────────────┼───────────┼──────────┼────────────┼────────────┼───────────────────────────────
  1  │ gpt-oss-120b-medium       │ 🟢 1/1 OK │ 1.842 s  │ 2.451 s    │ 24.5 tok/s │ "Hello! Nice to meet you."
  2  │ gemini-3.7-flash-low      │ 🟢 1/1 OK │ 0.412 s  │ 0.890 s    │ 48.2 tok/s │ "Hello! How can I assist?"
  3  │ gemini-3.8-flash-medium   │ 🟢 1/1 OK │ 0.380 s  │ 0.760 s    │ 56.1 tok/s │ "Greetings! Hope you are well."
  4  │ deepseek-r1-distill-70b   │ 🟢 1/1 OK │ 2.105 s  │ 3.920 s    │ 18.2 tok/s │ "Hello there! Ready to help."
  ───┴───────────────────────────┴───────────┴──────────┴────────────┴────────────┴───────────────────────────────
  ✨ Completed 4/4 benchmark runs in 8.02s

  📁 Exported Reports:
  ✔ Interactive Web UI report : file:///C:/Users/.../benchmark_report.html (Ctrl+Click to view)
  ✔ Markdown report          : file:///C:/Users/.../benchmark_report.md
  ✔ JSON report              : file:///C:/Users/.../benchmark_report.json
```

---

## Quickstart

Install globally once in your terminal:

```bash
# macOS / Linux
pip3 install git+https://github.com/mijanlab/LLMtest.git
# or with pipx (recommended for Homebrew / isolated CLI)
pipx install git+https://github.com/mijanlab/LLMtest.git

# Windows
pip install git+https://github.com/mijanlab/LLMtest.git
```

Launch the interactive prompt from anywhere:

```bash
llmtest
```

> [!TIP]
> The interactive prompt automatically queries `/models`, lets you optionally filter by keyword (e.g. `flash`, `free`, `gpt`), streams real-time latency stats, and generates a clickable interactive Web UI report!

---

## One-Line Run (No Install)

Run benchmarks directly in any terminal without cloning or saving files:

### macOS / Linux / Git Bash
```bash
# Interactive mode
curl -sSL https://raw.githubusercontent.com/mijanlab/LLMtest/main/test_all_models.py | python3

# Or with arguments directly
curl -sSL https://raw.githubusercontent.com/mijanlab/LLMtest/main/test_all_models.py | python3 - https://api.openai.com/v1 <your_api_key>
```

### Windows (PowerShell)
```powershell
# Interactive mode
irm https://raw.githubusercontent.com/mijanlab/LLMtest/main/test_all_models.py | py -

# Or with arguments directly
irm https://raw.githubusercontent.com/mijanlab/LLMtest/main/test_all_models.py | py - https://api.openai.com/v1 <your_api_key>
```

---

## CLI Usage

Pass arguments directly for CI/CD pipelines, scripted benchmarks, or fast terminal evaluations:

```bash
# Syntax: llmtest <endpoint | update | uninstall> [api_key] [model_filter] [concurrency]

# Benchmark all models
llmtest https://api.openai.com/v1 sk-...

# Filter specific models (e.g., only 'flash' or 'gpt-4o')
llmtest https://api.openai.com/v1 sk-... flash

# Free models on OpenRouter
llmtest https://openrouter.ai/api/v1 sk-... free

# Automatically open Web UI report in browser when finished
llmtest https://api.openai.com/v1 sk-... --open

# Update llmtest to the latest version
llmtest update

# Uninstall llmtest
llmtest uninstall
```

### Options & Flags

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `endpoint` | `string` | *(prompted)* | Base URL for OpenAI-compatible API (e.g. `https://api.openai.com/v1`) |
| `update` | `command` | — | Upgrade `llmtest` directly to the latest GitHub release |
| `uninstall` | `command` | — | Cleanly remove `llmtest` from your Python environment |
| `api_key` | `string` | *(prompted)* | Bearer authentication key (optional for local/unauthenticated endpoints) |
| `filter` | `string` | `""` | Substring match to filter model IDs (e.g. `claude`, `llama3`, `deepseek`) |
| `concurrency` | `int` | `3` | Number of concurrent requests to execute in parallel |
| `--prompt` | `string` | `"Say hello in 5 words"` | Custom evaluation prompt string |
| `--runs` | `int` | `1` | Number of test repetitions per model |
| `--timeout` | `float` | `35.0` | HTTP request timeout in seconds |
| `--report` / `--render` | `path` | `""` | Render HTML/MD/CSV reports from an existing benchmark JSON file |
| `--no-report` | `flag` | `False` | Disable writing report files to disk |
| `--open` | `flag` | `False` | Automatically open interactive HTML report in default browser |
| `--output-html` / `--html` | `string` | `"benchmark_report.html"` | Interactive HTML report destination |
| `--output-md` | `string` | `"benchmark_report.md"` | Markdown table report destination |
| `--output-csv` / `--csv` | `string` | `"benchmark_report.csv"` | Structured CSV report destination |
| `--output-json` | `string` | `"benchmark_report.json"` | Raw JSON report destination |

---

## Interactive Web Report

Every benchmark run generates a self-contained, standalone **`benchmark_report.html`** dashboard that requires zero backend servers or CDNs (works 100% offline):

* **Next-Gen Obsidian / Dark Glassmorphism UI**: High-contrast, executive-level dashboard with sleek luminous accents.
* **Interactive Visual Matrix**: Canvas-based TTFT latency vs throughput scatter plot with interactive hover tooltips and quadrant indicators.
* **Leaderboards & Analytics**: Live top streaming speed and lowest TTFT latency leaderboard bar charts.
* **Dual View Modes**: Seamless toggle between **Table View** and responsive **Bento Cards Grid View**.
* **Head-to-Head Model Comparison**: Select 2–4 models with checkboxes to compare metrics, latency, speed, and raw completions side-by-side in a comparison drawer.
* **Rich Model Inspection Modal**: Detailed modal displaying status, TTFT, throughput, total time, output preview with syntax styling, error diagnostics, and raw JSON payload.
* **Multi-Format Export**: 1-click Markdown table copy, Shareable Summary Card copy, CSV download, JSON export, and print-optimized PDF view.
* **Instant Search & Hotkeys**: Real-time debounce filter (`/` hotkey to focus search) and quick status chips (*All*, *Passed*, *Skipped*, *Failed*).

---

## Re-rendering Reports from JSON

You can re-generate or view reports from any existing `benchmark_report.json` without re-running models:

```bash
# Render HTML, Markdown, and CSV reports and open in browser
llmtest --report benchmark_report.json --open

# Or shorthand
llmtest benchmark_report.json
```

---

## Metrics Measured

| Metric | Measurement Method | Target Objective |
| :--- | :--- | :--- |
| **TTFT** | Request start $\rightarrow$ first streamed chunk byte | Measures initial perceived latency in UI / Chat |
| **Total Latency** | Wall-clock time from connection $\rightarrow$ stream close | Measures end-to-end task completion time |
| **Throughput** | Completed output tokens $\div$ generation time | Generation speed in `tokens/sec` |
| **Chunks/sec** | Streamed chunks $\div$ generation time | Measures stream buffer fragmentation |
| **Success Rate** | HTTP 200 + non-empty stream completion $\div$ total attempts | Identifies rate limits (429), timeouts, and 500s |

---

## Security

* **Zero Key Persistence**: API keys are held purely in volatile memory during benchmark runs. No credentials or requests are ever logged to disk or external servers.
* **Pure Standard Library Core**: Core benchmarking utilities use Python's native `urllib.request` and `asyncio`, eliminating third-party supply-chain footprint.
* **Self-Contained Offline Reports**: The generated HTML report has zero external CDN tracking and runs 100% offline.

---

<div align="center">
  <sub>Built with precision by <a href="https://github.com/mijanlab">@mijanlab</a> • Distributed under the MIT License</sub>
</div>

