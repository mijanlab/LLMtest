#!/usr/bin/env python3
"""
⚡ LLM Speed & Latency Benchmark (Standalone)
---------------------------------------------
Zero-dependency, cross-platform CLI tool for evaluating OpenAI-compatible endpoints.
Can be executed directly via:
  curl -sSL https://raw.githubusercontent.com/mijanlab/LLMtest/main/test_all_models.py | python3
"""

import os
import sys
import time
import json
import csv
import shutil
import argparse
import subprocess
import webbrowser
import statistics
import concurrent.futures
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Terminal ANSI styling helpers
def supports_color():
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.name == "nt":
        return (
            "ANSICON" in os.environ
            or "WT_SESSION" in os.environ
            or os.environ.get("TERM_PROGRAM") is not None
            or os.environ.get("TERM") == "xterm-256color"
            or (hasattr(sys, "getwindowsversion") and sys.getwindowsversion().major >= 10)
        )
    return True

USE_COLOR = supports_color()
CLR_RESET = "\033[0m" if USE_COLOR else ""
CLR_BOLD = "\033[1m" if USE_COLOR else ""
CLR_DIM = "\033[2m" if USE_COLOR else ""
CLR_CYAN = "\033[36m" if USE_COLOR else ""
CLR_GREEN = "\033[32m" if USE_COLOR else ""
CLR_YELLOW = "\033[33m" if USE_COLOR else ""
CLR_RED = "\033[31m" if USE_COLOR else ""
CLR_GRAY = "\033[90m" if USE_COLOR else ""

# Try importing requests; fallback to standard library urllib
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request
    import urllib.error

def normalize_urls(raw_endpoint: str):
    endpoint = (raw_endpoint or "").strip().rstrip("/")
    if not endpoint:
        return "", ""
    
    if endpoint.endswith("/chat/completions"):
        base = endpoint[:-len("/chat/completions")].rstrip("/")
        chat_url = endpoint
    elif endpoint.endswith("/models"):
        base = endpoint[:-len("/models")].rstrip("/")
        chat_url = f"{base}/chat/completions"
    else:
        base = endpoint
        chat_url = f"{base}/chat/completions"
        
    models_url = f"{base}/models"
    return models_url, chat_url

def http_get_json(url: str, api_key: str = "", timeout: int = 15):
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/mijanlab/LLMtest",
        "X-Title": "LLM Benchmark Suite"
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if HAS_REQUESTS:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()
    else:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")[:200]
            raise RuntimeError(f"HTTP {e.code}: {err_body}")

def fetch_available_models(models_url: str, api_key: str, timeout: int = 15):
    try:
        res = http_get_json(models_url, api_key, timeout=timeout)
        raw_list = []
        if isinstance(res, dict):
            raw_list = res.get("data") or res.get("models") or []
        elif isinstance(res, list):
            raw_list = res
            
        models = []
        for item in raw_list:
            if isinstance(item, str):
                models.append({"id": item, "name": item, "is_free": False})
            elif isinstance(item, dict):
                m_id = item.get("id") or item.get("name")
                if not m_id:
                    continue
                pricing = item.get("pricing") or {}
                prompt_price = float(pricing.get("prompt", 1) or 0)
                completion_price = float(pricing.get("completion", 1) or 0)
                is_free = (":free" in m_id) or (prompt_price == 0 and completion_price == 0 and bool(pricing))
                models.append({
                    "id": m_id,
                    "name": item.get("name") or m_id,
                    "is_free": is_free,
                    "context_length": item.get("context_length")
                })
        return models
    except Exception as e:
        print(f" {CLR_RED}✖ Error discovering models:{CLR_RESET} {e}")
        return []

def test_single_model_streaming(chat_url: str, model_id: str, api_key: str, prompt: str, system_prompt: str, max_tokens: int, timeout: int):
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/mijanlab/LLMtest",
        "X-Title": "LLM Benchmark Suite"
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_id,
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
        "max_tokens": max_tokens
    }

    start = time.perf_counter()
    first = None
    last = None
    chunks = 0
    accumulated_text = []
    usage_info = {}

    try:
        if HAS_REQUESTS:
            with requests.post(chat_url, headers=headers, json=payload, stream=True, timeout=timeout) as r:
                status = r.status_code
                if status != 200:
                    try:
                        err_json = r.json()
                        if isinstance(err_json, dict) and "error" in err_json:
                            err_val = err_json["error"]
                            if isinstance(err_val, dict) and "message" in err_val:
                                return {"ok": False, "error": f"HTTP {status}: {err_val['message']}"}
                            return {"ok": False, "error": f"HTTP {status}: {err_val}"}
                    except Exception:
                        pass
                    body = r.text[:150].strip()
                    return {"ok": False, "error": f"HTTP {status}: {body}"}

                line_iterator = r.iter_lines(decode_unicode=True)
                for raw in line_iterator:
                    if not raw or not raw.startswith("data:"):
                        continue
                    data = raw[5:].strip()
                    if data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue

                    if isinstance(obj, dict) and "error" in obj:
                        err_obj = obj["error"]
                        err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                        return {"ok": False, "error": f"Stream Error: {err_msg}"}

                    if isinstance(obj, dict) and obj.get("usage"):
                        usage_info = obj["usage"]

                    choices = obj.get("choices") or []
                    if choices:
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        text_piece = (
                            delta.get("content")
                            or delta.get("reasoning")
                            or delta.get("reasoning_content")
                            or delta.get("thought")
                            or delta.get("text")
                            or choice.get("text")
                        )

                        if not text_piece and choice.get("message"):
                            msg = choice.get("message") or {}
                            text_piece = msg.get("content") or msg.get("reasoning")

                        if text_piece:
                            now = time.perf_counter()
                            if first is None:
                                first = now
                            last = now
                            chunks += 1
                            accumulated_text.append(str(text_piece))
                end = time.perf_counter()
        else:
            req = urllib.request.Request(
                chat_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for line_bytes in resp:
                    raw = line_bytes.decode("utf-8", errors="ignore").strip()
                    if not raw or not raw.startswith("data:"):
                        continue
                    data = raw[5:].strip()
                    if data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue

                    if isinstance(obj, dict) and "error" in obj:
                        err_obj = obj["error"]
                        err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                        return {"ok": False, "error": f"Stream Error: {err_msg}"}

                    if isinstance(obj, dict) and obj.get("usage"):
                        usage_info = obj["usage"]

                    choices = obj.get("choices") or []
                    if choices:
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        text_piece = (
                            delta.get("content")
                            or delta.get("reasoning")
                            or delta.get("reasoning_content")
                            or delta.get("thought")
                            or delta.get("text")
                            or choice.get("text")
                        )
                        if not text_piece and choice.get("message"):
                            msg = choice.get("message") or {}
                            text_piece = msg.get("content") or msg.get("reasoning")

                        if text_piece:
                            now = time.perf_counter()
                            if first is None:
                                first = now
                            last = now
                            chunks += 1
                            accumulated_text.append(str(text_piece))
            end = time.perf_counter()

        if first is None:
            if not accumulated_text:
                return {"ok": False, "error": "No streamed tokens received"}
            first = end
            last = end

        ttft = first - start
        total = end - start
        gen = (last - first) if (last and last > first) else 0

        completion_tokens = usage_info.get("completion_tokens") if usage_info else None
        if completion_tokens and gen > 0:
            tps = completion_tokens / gen
        elif chunks > 1 and gen > 0:
            tps = chunks / gen
        else:
            tps = None

        full_text = "".join(accumulated_text).strip()
        preview = (full_text[:80] + "...") if len(full_text) > 80 else full_text

        return {
            "ok": True,
            "ttft": ttft,
            "total": total,
            "generation": gen,
            "chunks": chunks,
            "tps": tps,
            "completion_tokens": completion_tokens,
            "prompt_tokens": usage_info.get("prompt_tokens") if usage_info else None,
            "total_tokens": usage_info.get("total_tokens") if usage_info else None,
            "preview": preview
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def is_no_fund_error(err_str: str) -> bool:
    """Checks if an error string indicates insufficient funds, credits, or quota."""
    err_lower = (err_str or "").lower()
    indicators = [
        "402",
        "payment required",
        "insufficient_quota",
        "insufficient_funds",
        "insufficient funds",
        "insufficient credit",
        "out of credits",
        "out of credit",
        "no credit",
        "no credits",
        "balance is zero",
        "exceeded your current quota",
        "quota exceeded",
        "billing",
        "credits required",
        "unpaid",
        "fund"
    ]
    return any(ind in err_lower for ind in indicators)

def benchmark_model(chat_url: str, model_id: str, api_key: str, prompt: str, system_prompt: str, max_tokens: int, timeout: int, runs: int):
    run_results = []
    for i in range(runs):
        res = test_single_model_streaming(chat_url, model_id, api_key, prompt, system_prompt, max_tokens, timeout)
        res["run"] = i + 1
        run_results.append(res)

    good = [r for r in run_results if r.get("ok")]
    ttfts = [r["ttft"] for r in good if r.get("ttft") is not None]
    totals = [r["total"] for r in good if r.get("total") is not None]
    tpss = [r["tps"] for r in good if r.get("tps") is not None]

    errors = list({r.get("error") for r in run_results if not r.get("ok") and r.get("error")})
    sample_preview = next((r.get("preview") for r in good if r.get("preview")), None)

    # Detect if failure was purely due to missing funds/credits
    if not good and errors and all(is_no_fund_error(e) for e in errors):
        status = "SKIPPED"
        skip_reason = "Non-available fund (skipped)"
    elif len(good) == runs:
        status = "PASS"
        skip_reason = None
    elif len(good) > 0:
        status = "PARTIAL"
        skip_reason = None
    else:
        status = "FAIL"
        skip_reason = None

    return {
        "model": model_id,
        "runs": runs,
        "success": len(good),
        "failed": runs - len(good),
        "status": status,
        "skip_reason": skip_reason,
        "avg_ttft": statistics.mean(ttfts) if ttfts else None,
        "avg_total": statistics.mean(totals) if totals else None,
        "avg_tps": statistics.mean(tpss) if tpss else None,
        "sample_preview": sample_preview,
        "errors": errors,
        "details": run_results
    }

def print_table(results):
    """
    Renders a modern, cleanly aligned table with colored badges.
    """
    col_idx = 3
    col_model = 27
    col_status = 10
    col_ttft = 10
    col_total = 10
    col_tps = 12
    col_preview = 32

    sep = f"┌{'─'*(col_idx+2)}┬{'─'*(col_model+2)}┬{'─'*(col_status+2)}┬{'─'*(col_ttft+2)}┬{'─'*(col_total+2)}┬{'─'*(col_tps+2)}┬{'─'*(col_preview+2)}┐"
    mid_sep = f"├{'─'*(col_idx+2)}┼{'─'*(col_model+2)}┼{'─'*(col_status+2)}┼{'─'*(col_ttft+2)}┼{'─'*(col_total+2)}┼{'─'*(col_tps+2)}┼{'─'*(col_preview+2)}┤"
    bot_sep = f"└{'─'*(col_idx+2)}┴{'─'*(col_model+2)}┴{'─'*(col_status+2)}┴{'─'*(col_ttft+2)}┴{'─'*(col_total+2)}┴{'─'*(col_tps+2)}┴{'─'*(col_preview+2)}┘"

    header = f"│ {'#':<{col_idx}} │ {'Model ID':<{col_model}} │ {'Status':<{col_status}} │ {'TTFT':<{col_ttft}} │ {'Total':<{col_total}} │ {'Speed':<{col_tps}} │ {'Output Preview / Notes':<{col_preview}} │"

    print("\n" + sep)
    print(f"{CLR_BOLD}{header}{CLR_RESET}")
    print(mid_sep)

    for i, r in enumerate(results, 1):
        if r['status'] == "PASS":
            status_text = "🟢 PASS"
            status_display = f"{CLR_GREEN}{status_text:<{col_status}}{CLR_RESET}"
        elif r['status'] == "PARTIAL":
            status_text = "🟡 PARTIAL"
            status_display = f"{CLR_YELLOW}{status_text:<{col_status}}{CLR_RESET}"
        elif r['status'] == "SKIPPED":
            status_text = "⚪ SKIP"
            status_display = f"{CLR_GRAY}{status_text:<{col_status}}{CLR_RESET}"
        else:
            status_text = "🔴 FAIL"
            status_display = f"{CLR_RED}{status_text:<{col_status}}{CLR_RESET}"

        ttft_str = f"{r['avg_ttft']*1000:.0f} ms" if r['avg_ttft'] and r['avg_ttft'] < 1 else (f"{r['avg_ttft']:.3f} s" if r['avg_ttft'] else "—")
        total_str = f"{r['avg_total']:.3f} s" if r['avg_total'] else "—"
        tps_str = f"{r['avg_tps']:.1f} tok/s" if r['avg_tps'] else "—"

        if r['status'] == "PASS":
            preview = (r['sample_preview'] or "").replace("\n", " ")
            note = f'"{preview}"' if len(preview) <= (col_preview - 2) else f'"{preview[:col_preview-5]}..."'
        elif r['status'] == "SKIPPED":
            note = f"{CLR_GRAY}Non-available fund (skipped){CLR_RESET}"
        else:
            err_msg = "; ".join(r['errors']) or "Failed"
            clean_err = err_msg.replace("\n", " ")
            note = clean_err if len(clean_err) <= col_preview else f"{clean_err[:col_preview-3]}..."

        m_name = (r['model'][:col_model-3] + "...") if len(r['model']) > col_model else r['model']
        row = f"│ {i:<{col_idx}} │ {m_name:<{col_model}} │ {status_display} │ {ttft_str:<{col_ttft}} │ {total_str:<{col_total}} │ {tps_str:<{col_tps}} │ {note:<{col_preview}} │"
        print(row)

    print(bot_sep)

def print_summary_card(results, total_duration: float):
    """
    Prints a concise executive summary card of the benchmark results.
    """
    passed = [r for r in results if r['status'] == "PASS"]
    skipped = [r for r in results if r['status'] == "SKIPPED"]
    failed = [r for r in results if r['status'] == "FAIL"]
    total = len(results)
    pass_count = len(passed)
    skip_count = len(skipped)
    pass_pct = (pass_count / (total - skip_count) * 100) if (total - skip_count) > 0 else 0

    fastest_ttft = min((r for r in passed if r['avg_ttft'] is not None), key=lambda x: x['avg_ttft'], default=None)
    highest_tps = max((r for r in passed if r['avg_tps'] is not None), key=lambda x: x['avg_tps'], default=None)

    print(f"\n{CLR_BOLD}📊 Benchmark Summary{CLR_RESET}")
    print(f" {CLR_GRAY}•{CLR_RESET} {CLR_BOLD}Total Models Tested{CLR_RESET} : {total}")
    print(f" {CLR_GRAY}•{CLR_RESET} {CLR_BOLD}Success Rate       {CLR_RESET} : {CLR_GREEN if pass_pct == 100 else CLR_YELLOW}{pass_count}/{total - skip_count} active passed ({pass_pct:.0f}%){CLR_RESET}")
    if skip_count > 0:
        print(f" {CLR_GRAY}•{CLR_RESET} {CLR_BOLD}Skipped (No Funds) {CLR_RESET} : {CLR_GRAY}{skip_count} models (Non-available fund models are skipped){CLR_RESET}")
    if fastest_ttft:
        f_val = f"{fastest_ttft['avg_ttft']*1000:.0f} ms" if fastest_ttft['avg_ttft'] < 1 else f"{fastest_ttft['avg_ttft']:.3f} s"
        print(f" {CLR_GRAY}•{CLR_RESET} {CLR_BOLD}Fastest TTFT       {CLR_RESET} : {CLR_CYAN}{fastest_ttft['model']}{CLR_RESET} ({f_val})")
    if highest_tps:
        print(f" {CLR_GRAY}•{CLR_RESET} {CLR_BOLD}Highest Speed      {CLR_RESET} : {CLR_CYAN}{highest_tps['model']}{CLR_RESET} ({highest_tps['avg_tps']:.1f} tok/s)")
    print(f" {CLR_GRAY}•{CLR_RESET} {CLR_BOLD}Total Time Elapsed {CLR_RESET} : {total_duration:.2f}s")
    print(f"\n {CLR_DIM}ℹ️  Note: Non-available fund models are skipped.{CLR_RESET}\n")

def export_markdown_report(results, filepath: str, endpoint: str):
    passed_count = sum(1 for r in results if r.get('status') == 'PASS')
    skipped_count = sum(1 for r in results if r.get('status') == 'SKIPPED')
    failed_count = sum(1 for r in results if r.get('status') == 'FAIL')

    lines = [
        f"# LLM Models Benchmark Report",
        f"",
        f"- **Endpoint Tested**: `{endpoint}`",
        f"- **Tested At**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Total Models**: {len(results)}",
        f"- **Passed (Working)**: {passed_count}",
        f"- **Skipped (No Funds)**: {skipped_count}",
        f"- **Failed**: {failed_count}",
        f"",
        f"> ℹ️ **Note**: Non-available fund models are skipped from active benchmark runs.",
        f"",
        f"## Results Summary Table",
        f"",
        f"| # | Model ID | Status | TTFT (Time to First Token) | Total Time | Throughput | Output Preview / Notes |",
        f"|---|---|---|---|---|---|---|"
    ]

    for i, r in enumerate(results, 1):
        if r.get('status') == "PASS":
            status_badge = f"🟢 {r.get('success', 1)}/{r.get('runs', 1)} OK"
        elif r.get('status') == "PARTIAL":
            status_badge = f"🟡 {r.get('success', 0)}/{r.get('runs', 1)} Partial"
        elif r.get('status') == "SKIPPED":
            status_badge = f"⚪ Skipped"
        else:
            status_badge = f"🔴 0/{r.get('runs', 1)} FAIL"

        ttft_str = f"{r['avg_ttft']*1000:.0f} ms" if r.get('avg_ttft') and r['avg_ttft'] < 1 else (f"{r['avg_ttft']:.3f} s" if r.get('avg_ttft') else "—")
        total_str = f"{r['avg_total']:.3f} s" if r.get('avg_total') else "—"
        tps_str = f"{r['avg_tps']:.1f} tok/s" if r.get('avg_tps') else "—"
        
        if r.get('status') == "PASS":
            preview = (r.get('sample_preview') or "").replace("|", "\\|").replace("\n", " ")
            note = f'"{preview}"'
        elif r.get('status') == "SKIPPED":
            note = "Non-available fund (skipped)"
        else:
            note = ("; ".join(r.get('errors', [])) or "Failed").replace("|", "\\|").replace("\n", " ")

        lines.append(f"| {i} | `{r['model']}` | {status_badge} | {ttft_str} | {total_str} | {tps_str} | {note[:65]} |")

    lines.append("")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f" {CLR_GREEN}✔{CLR_RESET} Markdown report : {CLR_CYAN}{os.path.abspath(filepath)}{CLR_RESET}")


def export_csv_report(results, filepath: str, endpoint: str):
    """
    Exports benchmark results to a structured CSV file.
    """
    import csv
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Model ID", "Status", "Success Runs", "Total Runs", "Avg TTFT (s)", "Avg Total Time (s)", "Avg Speed (tok/s)", "Preview / Note", "Endpoint", "Timestamp"])
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        for r in results:
            note = r.get("sample_preview") or ("; ".join(r.get("errors", [])) if r.get("errors") else "")
            if r.get("status") == "SKIPPED":
                note = "Non-available fund / skipped"
            writer.writerow([
                r.get("model", ""),
                r.get("status", ""),
                r.get("success", 0),
                r.get("runs", 0),
                f"{r['avg_ttft']:.4f}" if r.get("avg_ttft") is not None else "",
                f"{r['avg_total']:.4f}" if r.get("avg_total") is not None else "",
                f"{r['avg_tps']:.2f}" if r.get("avg_tps") is not None else "",
                note,
                endpoint,
                timestamp
            ])
    print(f" {CLR_GREEN}✔{CLR_RESET} CSV report      : {CLR_CYAN}{os.path.abspath(filepath)}{CLR_RESET}")


HTML_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>⚡ LLMtest Benchmark Report — {ENDPOINT}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #060907;
      --card: #0b120d;
      --card-muted: #0f1811;
      --card-hover: #142218;
      --border: #1a2d1f;
      --border-subtle: #122016;
      --border-glow: rgba(74, 222, 128, 0.3);
      --text: #f0fdf4;
      --text-muted: #8ba391;
      --text-dim: #506556;
      --primary: #4ade80;
      --primary-fg: #050806;
      --neon-green: #4ade80;
      --neon-glow: 0 0 16px rgba(74, 222, 128, 0.25);
      --emerald: #4ade80;
      --sky: #38bdf8;
      --amber: #fbbf24;
      --rose: #f43f5e;
      --radius: 12px;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }
    body {
      background-color: var(--bg);
      background-image: 
        radial-gradient(circle at 50% 0%, rgba(34, 197, 94, 0.12) 0%, transparent 60%),
        radial-gradient(circle at 80% 20%, rgba(74, 222, 128, 0.05) 0%, transparent 40%);
      background-attachment: fixed;
      color: var(--text);
      font-family: var(--font-sans);
      -webkit-font-smoothing: antialiased;
      line-height: 1.5;
      padding: 36px 20px 80px;
      min-height: 100vh;
    }
    .container { max-width: 1320px; margin: 0 auto; }

    /* Header */
    .header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 26px;
      padding-bottom: 22px;
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
      gap: 16px;
    }
    .brand-title {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.03em;
      color: #ffffff;
    }
    .brand-title .brand-accent {
      color: var(--neon-green);
      text-shadow: 0 0 12px rgba(74, 222, 128, 0.4);
    }
    .brand-icon {
      width: 34px;
      height: 34px;
      background: #0f1a12;
      border: 1px solid var(--neon-green);
      border-radius: 10px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--neon-green);
      box-shadow: 0 0 15px rgba(74, 222, 128, 0.3);
    }
    .brand-badge {
      font-size: 11px;
      font-weight: 600;
      padding: 3px 9px;
      background: rgba(74, 222, 128, 0.08);
      border: 1px solid rgba(74, 222, 128, 0.25);
      border-radius: 20px;
      color: var(--neon-green);
      letter-spacing: 0.02em;
    }
    .header-sub {
      color: var(--text-muted);
      font-size: 13.5px;
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 8px;
    }
    .endpoint-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #0d1510;
      border: 1px solid var(--border);
      padding: 4px 11px;
      border-radius: 20px;
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--neon-green);
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .endpoint-pill:hover {
      background: #142218;
      border-color: var(--neon-green);
      box-shadow: 0 0 10px rgba(74, 222, 128, 0.2);
    }
    .timestamp-text {
      color: var(--text-dim);
      font-size: 12px;
    }

    .header-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #0d1510;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 7px 13px;
      border-radius: 20px;
      font-size: 12.5px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
      user-select: none;
    }
    .btn:hover {
      background: #16241a;
      border-color: rgba(74, 222, 128, 0.4);
      color: #fff;
    }
    .btn:active { transform: scale(0.98); }
    .btn-primary {
      background: var(--neon-green);
      color: #050806;
      border-color: var(--neon-green);
      font-weight: 700;
      box-shadow: 0 0 16px rgba(74, 222, 128, 0.3);
    }
    .btn-primary:hover {
      background: #86efac;
      border-color: #86efac;
      color: #050806;
      box-shadow: 0 0 20px rgba(74, 222, 128, 0.5);
    }

    /* Bento KPI Grid */
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }
    .kpi-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 18px 20px;
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.15s ease;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }
    .kpi-card:hover {
      border-color: rgba(74, 222, 128, 0.35);
      box-shadow: 0 6px 25px rgba(0,0,0,0.5), 0 0 15px rgba(74, 222, 128, 0.08);
      transform: translateY(-1px);
    }
    .kpi-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
    }
    .kpi-label {
      font-size: 11.5px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-dim);
    }
    .kpi-icon {
      color: var(--neon-green);
      display: flex;
      align-items: center;
    }
    .kpi-value {
      font-size: 28px;
      font-weight: 800;
      letter-spacing: -0.03em;
      color: var(--text);
      font-feature-settings: "tnum";
      font-variant-numeric: tabular-nums;
      margin-bottom: 4px;
    }
    .kpi-sub {
      font-size: 12px;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .kpi-progress {
      height: 4px;
      background: #121c14;
      border-radius: 2px;
      overflow: hidden;
      margin-top: 10px;
      display: flex;
    }
    .kpi-prog-pass { background: var(--neon-green); box-shadow: 0 0 8px var(--neon-green); }
    .kpi-prog-skip { background: #405145; }
    .kpi-prog-fail { background: var(--rose); }

    /* View Mode Tabs */
    .view-switcher-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }
    .nav-tabs {
      display: inline-flex;
      background: #0d1510;
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 3px;
      gap: 2px;
    }
    .nav-tab {
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 6px 14px;
      border-radius: 16px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
      user-select: none;
    }
    .nav-tab:hover { color: var(--text); }
    .nav-tab.active {
      background: #17261c;
      color: #fff;
      border: 1px solid rgba(74, 222, 128, 0.3);
      box-shadow: 0 1px 4px rgba(0,0,0,0.4);
    }

    /* Charts Section */
    .charts-container {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 16px;
      margin-bottom: 24px;
    }
    @media (max-width: 960px) {
      .charts-container { grid-template-columns: 1fr; }
    }
    .chart-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }
    .chart-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }
    .chart-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .chart-sub {
      font-size: 11.5px;
      color: var(--text-dim);
    }
    .scatter-canvas-wrap {
      position: relative;
      width: 100%;
      height: 280px;
    }
    canvas#scatterCanvas {
      width: 100%;
      height: 100%;
      display: block;
      cursor: crosshair;
    }
    .chart-tooltip {
      position: absolute;
      background: #0f1811;
      border: 1px solid var(--neon-green);
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 12px;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.1s ease;
      z-index: 10;
      box-shadow: 0 10px 25px rgba(0,0,0,0.7), 0 0 12px rgba(74, 222, 128, 0.2);
    }

    /* Leaderboard Bars */
    .leaderboard-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-height: 280px;
      overflow-y: auto;
      padding-right: 4px;
    }
    .leader-row {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 12.5px;
    }
    .leader-rank {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-dim);
      width: 18px;
      text-align: center;
    }
    .leader-name {
      width: 140px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text);
    }
    .leader-bar-wrap {
      flex: 1;
      height: 6px;
      background: #121c14;
      border-radius: 3px;
      overflow: hidden;
    }
    .leader-bar-fill {
      height: 100%;
      background: linear-gradient(90deg, #22c55e, #86efac);
      border-radius: 3px;
      box-shadow: 0 0 8px rgba(74, 222, 128, 0.4);
      transition: width 0.3s ease;
    }
    .leader-val {
      font-family: var(--font-mono);
      font-size: 11.5px;
      color: var(--neon-green);
      width: 65px;
      text-align: right;
    }

    /* Controls Bar */
    .controls {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }
    .search-wrapper {
      position: relative;
      flex: 1;
      max-width: 380px;
      min-width: 240px;
    }
    .search-icon {
      position: absolute;
      left: 12px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-dim);
      pointer-events: none;
      display: flex;
      align-items: center;
    }
    .search-input {
      width: 100%;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 8px 36px 8px 36px;
      color: var(--text);
      font-size: 13px;
      font-family: inherit;
      outline: none;
      transition: all 0.15s ease;
    }
    .search-input:focus {
      border-color: var(--neon-green);
      box-shadow: 0 0 12px rgba(74, 222, 128, 0.2);
    }
    .search-kbd {
      position: absolute;
      right: 10px;
      top: 50%;
      transform: translateY(-50%);
      background: #0f1811;
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 1px 5px;
      font-size: 11px;
      color: var(--text-dim);
      font-family: var(--font-mono);
      pointer-events: none;
    }

    .filter-chips {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .chip {
      background: #0d1510;
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 5px 12px;
      font-size: 12px;
      color: var(--text-muted);
      cursor: pointer;
      transition: all 0.15s ease;
      user-select: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .chip:hover { color: var(--text); border-color: rgba(74, 222, 128, 0.35); }
    .chip.active {
      background: #17261c;
      color: #fff;
      border-color: var(--neon-green);
      box-shadow: 0 0 10px rgba(74, 222, 128, 0.15);
    }
    .chip-count {
      font-size: 10.5px;
      padding: 1px 6px;
      background: rgba(0, 0, 0, 0.4);
      border-radius: 10px;
      font-family: var(--font-mono);
      color: var(--neon-green);
    }

    /* Table View */
    .table-container {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
      box-shadow: 0 4px 25px rgba(0, 0, 0, 0.45);
    }
    .table-scroll {
      overflow-x: auto;
      width: 100%;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 13.5px;
    }
    thead th {
      background: #0a110c;
      color: var(--text-muted);
      font-size: 11.5px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 11px 14px;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
      transition: color 0.15s ease;
    }
    thead th:hover { color: var(--text); }
    thead th .sort-indicator {
      display: inline-block;
      margin-left: 4px;
      font-size: 10px;
      color: var(--neon-green);
    }
    tbody tr {
      border-bottom: 1px solid var(--border-subtle);
      transition: background-color 0.12s ease;
    }
    tbody tr:last-child { border-bottom: none; }
    tbody tr:hover { background-color: rgba(23, 38, 28, 0.45); }
    tbody td {
      padding: 11px 14px;
      vertical-align: middle;
    }

    /* Badges & Pills */
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 3px 8px;
      border-radius: 20px;
      font-size: 11.5px;
      font-weight: 600;
      font-family: var(--font-mono);
      letter-spacing: 0.02em;
    }
    .badge-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
    }
    .badge-pass {
      background: rgba(74, 222, 128, 0.1);
      color: var(--neon-green);
      border: 1px solid rgba(74, 222, 128, 0.3);
    }
    .badge-pass .badge-dot { background: var(--neon-green); box-shadow: 0 0 8px var(--neon-green); }
    .badge-skip {
      background: rgba(113, 113, 122, 0.12);
      color: #a1a1aa;
      border: 1px solid rgba(113, 113, 122, 0.25);
    }
    .badge-skip .badge-dot { background: #71717a; }
    .badge-fail {
      background: rgba(244, 63, 94, 0.1);
      color: var(--rose);
      border: 1px solid rgba(244, 63, 94, 0.25);
    }
    .badge-fail .badge-dot { background: var(--rose); }
    .badge-par {
      background: rgba(245, 158, 11, 0.1);
      color: var(--amber);
      border: 1px solid rgba(245, 158, 11, 0.25);
    }
    .badge-par .badge-dot { background: var(--amber); }

    .rank-badge {
      font-size: 11px;
      font-weight: 700;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-family: var(--font-mono);
    }
    .rank-1 { background: rgba(74, 222, 128, 0.2); color: var(--neon-green); border: 1px solid var(--neon-green); box-shadow: 0 0 8px rgba(74, 222, 128, 0.3); }
    .rank-2 { background: rgba(148, 163, 184, 0.2); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.4); }
    .rank-3 { background: rgba(180, 83, 9, 0.2); color: #d97706; border: 1px solid rgba(180, 83, 9, 0.4); }
    .rank-other { color: var(--text-dim); }

    .model-pill {
      font-family: var(--font-mono);
      font-weight: 500;
      font-size: 12.5px;
      color: var(--text);
      background: #0d1510;
      border: 1px solid var(--border);
      padding: 3px 8px;
      border-radius: 6px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .copy-mini {
      color: var(--text-dim);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      transition: color 0.15s ease;
    }
    .copy-mini:hover { color: var(--neon-green); }

    .mono-cell {
      font-family: var(--font-mono);
      font-size: 12.5px;
      color: var(--text);
      font-variant-numeric: tabular-nums;
    }
    .meter-wrap {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .meter-bar-bg {
      height: 4px;
      background: #121c14;
      border-radius: 2px;
      width: 75px;
      overflow: hidden;
    }
    .meter-bar-fill-ttft { height: 100%; background: #38bdf8; border-radius: 2px; }
    .meter-bar-fill-speed { height: 100%; background: var(--neon-green); box-shadow: 0 0 6px var(--neon-green); border-radius: 2px; }

    .preview-truncate {
      color: var(--text-muted);
      font-size: 12.5px;
      max-width: 300px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* Bento Grid Mode */
    .bento-cards-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 14px;
    }
    .bento-model-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.15s ease;
      position: relative;
    }
    .bento-model-card:hover {
      border-color: rgba(74, 222, 128, 0.4);
      transform: translateY(-2px);
      box-shadow: 0 8px 25px rgba(0,0,0,0.5), 0 0 15px rgba(74, 222, 128, 0.1);
    }
    .card-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .card-metrics-3 {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
      margin-bottom: 12px;
      background: #0d1510;
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 8px 10px;
    }
    .card-metric-col {
      display: flex;
      flex-direction: column;
    }
    .card-metric-lbl {
      font-size: 10.5px;
      color: var(--text-dim);
      font-weight: 600;
      text-transform: uppercase;
    }
    .card-metric-val {
      font-size: 13.5px;
      font-weight: 700;
      font-family: var(--font-mono);
      margin-top: 2px;
    }
    .card-preview-box {
      font-size: 12px;
      color: var(--text-muted);
      background: #060907;
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 8px 10px;
      height: 60px;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      line-height: 1.4;
      margin-bottom: 12px;
    }
    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    /* Floating Compare Bar */
    .compare-float-bar {
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%) translateY(100px);
      background: #0d1610;
      border: 1px solid var(--neon-green);
      border-radius: 30px;
      padding: 10px 20px;
      display: flex;
      align-items: center;
      gap: 14px;
      box-shadow: 0 10px 35px rgba(0,0,0,0.8), 0 0 20px rgba(74, 222, 128, 0.3);
      z-index: 100;
      transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .compare-float-bar.show { transform: translateX(-50%) translateY(0); }
    .compare-count-text {
      font-size: 13.5px;
      font-weight: 600;
      color: var(--text);
    }

    /* Modal / Dialog */
    .modal-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.8);
      backdrop-filter: blur(10px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 999;
      padding: 16px;
    }
    .modal-overlay.open { display: flex; }
    .modal-card {
      background: #0a110c;
      border: 1px solid rgba(74, 222, 128, 0.35);
      border-radius: 16px;
      width: 100%;
      max-width: 720px;
      max-height: 88vh;
      overflow-y: auto;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.85), 0 0 30px rgba(74, 222, 128, 0.15);
      animation: modalPop 0.15s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .modal-compare-card {
      max-width: 1100px;
    }
    @keyframes modalPop {
      from { transform: scale(0.96); opacity: 0; }
      to { transform: scale(1); opacity: 1; }
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      padding: 20px 22px 16px;
      border-bottom: 1px solid var(--border);
    }
    .modal-close-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 20px;
      line-height: 1;
      padding: 4px;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .modal-close-btn:hover { background: #16241a; color: #fff; }
    .modal-body {
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    .code-box {
      background: #060907;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      font-family: var(--font-mono);
      font-size: 12.5px;
      line-height: 1.6;
      color: #e4e4e7;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 280px;
      overflow-y: auto;
    }

    /* Comparison Grid */
    .compare-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
    }
    .compare-col {
      background: #0d1510;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .compare-col-header {
      font-weight: 700;
      font-family: var(--font-mono);
      font-size: 13.5px;
      color: var(--text);
      border-bottom: 1px solid var(--border-subtle);
      padding-bottom: 8px;
    }

    /* Toast */
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #0d1610;
      border: 1px solid var(--neon-green);
      color: var(--text);
      padding: 10px 18px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.8), 0 0 15px rgba(74, 222, 128, 0.3);
      opacity: 0;
      transform: translateY(10px);
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
      pointer-events: none;
      z-index: 1000;
    }
    .toast.show { opacity: 1; transform: translateY(0); }

    /* Footer */
    .footer {
      margin-top: 40px;
      text-align: center;
      color: var(--text-dim);
      font-size: 12.5px;
    }
    .footer a { color: var(--neon-green); text-decoration: underline; text-underline-offset: 3px; }
    .footer a:hover { color: #86efac; }

    /* Print Styles */
    @media print {
      body { background: #fff; color: #000; padding: 0; background-image: none; }
      .header-actions, .controls, .compare-float-bar, .modal-overlay, .toast, .nav-tabs { display: none !important; }
      .kpi-card, .table-container, .chart-card { border: 1px solid #ddd; box-shadow: none; }
      table th { background: #f3f4f6; color: #000; }
      table td { color: #111; }
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <header class="header">
      <div>
        <div class="brand-title">
          <span class="brand-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="12" width="4" height="8" rx="1"></rect><rect x="10" y="8" width="4" height="12" rx="1"></rect><rect x="17" y="4" width="4" height="16" rx="1"></rect></svg>
          </span>
          <span>LLM<span class="brand-accent">test</span></span>
          <span class="brand-badge">Benchmark Suite</span>
        </div>
        <div class="header-sub">
          <span class="endpoint-pill" onclick="copyEndpoint()" title="Click to copy endpoint URL">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
            <span id="ep-display">{ENDPOINT}</span>
          </span>
          <span class="timestamp-text" id="timestamp-display"></span>
        </div>
      </div>
      <div class="header-actions">
        <button class="btn" onclick="copyMarkdown()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>
          Markdown
        </button>
        <button class="btn" onclick="copySummaryCard()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
          Share Card
        </button>
        <button class="btn" onclick="downloadCSV()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
          CSV
        </button>
        <button class="btn btn-primary" onclick="downloadJSON()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" x2="12" y1="15" y2="3"></line></svg>
          Export JSON
        </button>
        <button class="btn" onclick="window.print()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect width="12" height="8" x="6" y="14"></rect></svg>
        </button>
      </div>
    </header>

    <!-- Bento KPI Grid -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-top">
          <span class="kpi-label">Tested Models</span>
          <span class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path></svg></span>
        </div>
        <div class="kpi-value" id="kpi-total">0</div>
        <div class="kpi-sub" id="kpi-pass-rate">0 passed, 0 skipped</div>
        <div class="kpi-progress">
          <div class="kpi-prog-pass" id="bar-pass" style="width: 0%;"></div>
          <div class="kpi-prog-skip" id="bar-skip" style="width: 0%;"></div>
          <div class="kpi-prog-fail" id="bar-fail" style="width: 0%;"></div>
        </div>
      </div>

      <div class="kpi-card">
        <div class="kpi-top">
          <span class="kpi-label">Fastest First Token</span>
          <span class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 14 14"></polyline></svg></span>
        </div>
        <div class="kpi-value" style="color: var(--neon-green); text-shadow: 0 0 12px rgba(74, 222, 128, 0.4);" id="kpi-ttft">—</div>
        <div class="kpi-sub" id="kpi-ttft-model">—</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-top">
          <span class="kpi-label">Peak Throughput</span>
          <span class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m13 2-2 2.5V8l2-2.5V2Z"></path><path d="m19 10-2.5-2V5.5L19 8v2Z"></path><circle cx="12" cy="14" r="8"></circle><line x1="12" y1="14" x2="16" y2="10"></line></svg></span>
        </div>
        <div class="kpi-value" style="color: var(--neon-green); text-shadow: 0 0 12px rgba(74, 222, 128, 0.4);" id="kpi-speed">—</div>
        <div class="kpi-sub" id="kpi-speed-model">—</div>
      </div>

      <div class="kpi-card">
        <div class="kpi-top">
          <span class="kpi-label">Active Pass Rate</span>
          <span class="kpi-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg></span>
        </div>
        <div class="kpi-value" style="color: var(--neon-green);" id="kpi-success">0%</div>
        <div class="kpi-sub" id="kpi-failed-count">0 skipped / 0 failed</div>
      </div>
    </div>

    <!-- Visual Charts Row -->
    <div class="charts-container" id="chartsSection">
      <!-- Scatter Plot -->
      <div class="chart-card">
        <div class="chart-header">
          <div>
            <div class="chart-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--neon-green)" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M3 3v18h18"></path></svg>
              Latency vs Throughput Matrix
            </div>
            <div class="chart-sub">Hover points to inspect model performance quadrant</div>
          </div>
        </div>
        <div class="scatter-canvas-wrap">
          <canvas id="scatterCanvas"></canvas>
          <div class="chart-tooltip" id="chartTooltip"></div>
        </div>
      </div>

      <!-- Top Speed Leaderboard -->
      <div class="chart-card">
        <div class="chart-header">
          <div>
            <div class="chart-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--neon-green)" stroke-width="2"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"></path><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"></path><path d="M4 22h16"></path><path d="M10 14.66V17c0 .55-.45 1-1 1H7c-.55 0-1-.45-1-1v-2.34"></path><path d="M14 14.66V17c0 .55.45 1 1 1h2c.55 0 1-.45 1-1v-2.34"></path></svg>
              Speed Leaderboard (Tokens/sec)
            </div>
            <div class="chart-sub">Top fastest streaming models</div>
          </div>
        </div>
        <div class="leaderboard-list" id="leaderboardList"></div>
      </div>
    </div>

    <!-- View Switcher & Controls -->
    <div class="view-switcher-bar">
      <div class="nav-tabs">
        <button class="nav-tab active" id="tab-table-view" onclick="setViewMode('table')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="18" x="3" y="3" rx="2"></rect><path d="M3 9h18"></path><path d="M3 15h18"></path><path d="M9 3v18"></path></svg>
          Table View
        </button>
        <button class="nav-tab" id="tab-grid-view" onclick="setViewMode('grid')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="7" height="7" x="3" y="3" rx="1"></rect><rect width="7" height="7" x="14" y="3" rx="1"></rect><rect width="7" height="7" x="14" y="14" rx="1"></rect><rect width="7" height="7" x="3" y="14" rx="1"></rect></svg>
          Bento Cards
        </button>
      </div>

      <div class="filter-chips">
        <div class="chip active" onclick="setFilter('ALL', this)">All <span class="chip-count" id="count-all">0</span></div>
        <div class="chip" onclick="setFilter('PASS', this)">Passed <span class="chip-count" id="count-pass">0</span></div>
        <div class="chip" onclick="setFilter('SKIPPED', this)">Skipped <span class="chip-count" id="count-skip">0</span></div>
        <div class="chip" onclick="setFilter('FAIL', this)">Failed <span class="chip-count" id="count-fail">0</span></div>
      </div>
    </div>

    <div class="controls">
      <div class="search-wrapper">
        <span class="search-icon">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
        </span>
        <input type="text" class="search-input" id="searchInput" placeholder="Search models or responses... (Press '/' to focus)" oninput="renderAll()" />
        <span class="search-kbd">/</span>
      </div>

      <div style="display: flex; gap: 8px; align-items: center;">
        <select class="btn" id="sortSelect" onchange="handleSortSelect(this.value)" style="padding: 7px 12px;">
          <option value="avg_ttft-asc">Sort: Fastest TTFT</option>
          <option value="avg_tps-desc">Sort: Highest Speed</option>
          <option value="avg_total-asc">Sort: Total Duration</option>
          <option value="model-asc">Sort: Model ID (A-Z)</option>
          <option value="status-asc">Sort: Status</option>
        </select>
      </div>
    </div>

    <!-- Table Container -->
    <div class="table-container" id="tableViewSection">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th style="width: 36px;"><input type="checkbox" id="selectAllBox" onchange="toggleSelectAll(this)" /></th>
              <th style="width: 44px;">#</th>
              <th onclick="sortTable('model')">Model ID <span id="sort-model" class="sort-indicator"></span></th>
              <th onclick="sortTable('status')">Status <span id="sort-status" class="sort-indicator"></span></th>
              <th onclick="sortTable('avg_ttft')">TTFT <span id="sort-avg_ttft" class="sort-indicator"></span></th>
              <th onclick="sortTable('avg_total')">Total Time <span id="sort-avg_total" class="sort-indicator"></span></th>
              <th onclick="sortTable('avg_tps')">Speed <span id="sort-avg_tps" class="sort-indicator"></span></th>
              <th>Output Preview / Error Note</th>
              <th style="text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody id="tableBody"></tbody>
        </table>
      </div>
    </div>

    <!-- Bento Cards Container -->
    <div class="bento-cards-grid" id="gridViewSection" style="display: none;"></div>

    <!-- Footer -->
    <footer class="footer">
      Generated by <a href="https://github.com/mijanlab/LLMtest" target="_blank">LLMtest</a> • TEST / COMPARE / CHOOSE BETTER
    </footer>
  </div>

  <!-- Floating Multi-Model Comparison Bar -->
  <div class="compare-float-bar" id="compareBar">
    <span class="compare-count-text" id="compareCountText">0 models selected</span>
    <button class="btn btn-primary" onclick="openComparisonModal()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 3h5v5"></path><path d="M8 3H3v5"></path><path d="M12 22v-8"></path><path d="m8 7 4 4 4-4"></path></svg>
      Compare Side-by-Side
    </button>
    <button class="btn" onclick="clearSelection()" style="padding: 5px 10px;">Clear</button>
  </div>

  <!-- Model Detail Modal -->
  <div class="modal-overlay" id="modalOverlay" onclick="closeModal(event)">
    <div class="modal-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div>
          <h3 id="modalTitle" style="font-size: 17px; font-weight: 700; letter-spacing: -0.02em;"></h3>
          <p id="modalSubtitle" style="color: var(--text-dim); font-size: 12px; margin-top: 2px;"></p>
        </div>
        <button class="modal-close-btn" onclick="closeModalDirect()">&times;</button>
      </div>
      <div class="modal-body" id="modalBody"></div>
    </div>
  </div>

  <!-- Comparison Modal -->
  <div class="modal-overlay" id="compareModalOverlay" onclick="closeCompareModal(event)">
    <div class="modal-card modal-compare-card" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div>
          <h3 style="font-size: 17px; font-weight: 700;">⚖️ Side-by-Side Model Comparison</h3>
          <p style="color: var(--text-dim); font-size: 12px; margin-top: 2px;">Direct head-to-head performance breakdown</p>
        </div>
        <button class="modal-close-btn" onclick="closeCompareModalDirect()">&times;</button>
      </div>
      <div class="modal-body">
        <div class="compare-grid" id="compareGrid"></div>
      </div>
    </div>
  </div>

  <!-- Toast Notification -->
  <div class="toast" id="toast">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--neon-green)" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
    <span id="toastMsg">Copied</span>
  </div>

  <script>
    const DATA = {DATA_JSON};
    let currentStatusFilter = 'ALL';
    let sortColumn = 'avg_ttft';
    let sortDirection = 'asc';
    let currentViewMode = 'table';
    let selectedModels = new Set();

    document.getElementById('ep-display').textContent = DATA.endpoint || '{ENDPOINT}';
    document.getElementById('timestamp-display').textContent = DATA.tested_at ? (typeof DATA.tested_at === 'number' ? new Date(DATA.tested_at * 1000).toLocaleString() : DATA.tested_at) : new Date().toLocaleString();

    const results = DATA.results || [];
    const passed = results.filter(r => r.status === 'PASS');
    const skipped = results.filter(r => r.status === 'SKIPPED');
    const failed = results.filter(r => r.status === 'FAIL');
    const total = results.length;
    const passCount = passed.length;
    const skipCount = skipped.length;
    const failCount = failed.length;
    const activeTotal = total - skipCount;
    const passPct = activeTotal ? Math.round((passCount / activeTotal) * 100) : 0;

    document.getElementById('count-all').textContent = total;
    document.getElementById('count-pass').textContent = passCount;
    document.getElementById('count-skip').textContent = skipCount;
    document.getElementById('count-fail').textContent = failCount;

    document.getElementById('kpi-total').textContent = total;
    document.getElementById('kpi-pass-rate').textContent = `${passCount} passed, ${skipCount} skipped`;
    document.getElementById('kpi-success').textContent = `${passPct}% (${passCount}/${activeTotal})`;
    document.getElementById('kpi-failed-count').textContent = `${skipCount} skipped / ${failCount} failed`;

    if (total > 0) {
      document.getElementById('bar-pass').style.width = `${(passCount / total) * 100}%`;
      document.getElementById('bar-skip').style.width = `${(skipCount / total) * 100}%`;
      document.getElementById('bar-fail').style.width = `${(failCount / total) * 100}%`;
    }

    const ttftList = passed.filter(r => r.avg_ttft !== null);
    if (ttftList.length) {
      ttftList.sort((a, b) => a.avg_ttft - b.avg_ttft);
      const best = ttftList[0];
      const val = best.avg_ttft < 1 ? `${Math.round(best.avg_ttft * 1000)} ms` : `${best.avg_ttft.toFixed(2)} s`;
      document.getElementById('kpi-ttft').textContent = val;
      document.getElementById('kpi-ttft-model').textContent = `🏆 ${best.model}`;
    }

    const tpsList = passed.filter(r => r.avg_tps !== null);
    if (tpsList.length) {
      tpsList.sort((a, b) => b.avg_tps - a.avg_tps);
      const best = tpsList[0];
      document.getElementById('kpi-speed').textContent = `${best.avg_tps.toFixed(1)} tok/s`;
      document.getElementById('kpi-speed-model').textContent = `⚡ ${best.model}`;
    }

    // Render Speed Leaderboard
    const lbContainer = document.getElementById('leaderboardList');
    if (tpsList.length === 0) {
      lbContainer.innerHTML = '<div style="color: var(--text-dim); text-align: center; padding: 20px;">No speed data available</div>';
    } else {
      const top10 = tpsList.slice(0, 10);
      const maxLBSpeed = top10[0].avg_tps || 1;
      top10.forEach((r, i) => {
        const pct = Math.min(100, Math.round((r.avg_tps / maxLBSpeed) * 100));
        const row = document.createElement('div');
        row.className = 'leader-row';
        row.innerHTML = `
          <span class="leader-rank">${i + 1}</span>
          <span class="leader-name" title="${r.model}">${r.model}</span>
          <div class="leader-bar-wrap"><div class="leader-bar-fill" style="width: ${pct}%;"></div></div>
          <span class="leader-val">${r.avg_tps.toFixed(1)} t/s</span>
        `;
        lbContainer.appendChild(row);
      });
    }

    // Interactive Scatter Plot Canvas
    function initScatterPlot() {
      const canvas = document.getElementById('scatterCanvas');
      const ctx = canvas.getContext('2d');
      const tooltip = document.getElementById('chartTooltip');

      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);

      const w = rect.width;
      const h = rect.height;
      const pad = { top: 20, right: 30, bottom: 35, left: 45 };

      const valid = passed.filter(r => r.avg_ttft !== null && r.avg_tps !== null);
      if (!valid.length) {
        ctx.fillStyle = '#506556';
        ctx.font = '13px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No completed latency benchmarks to plot', w / 2, h / 2);
        return;
      }

      const maxTTFT = Math.max(...valid.map(r => r.avg_ttft)) * 1.15 || 1;
      const maxTPS = Math.max(...valid.map(r => r.avg_tps)) * 1.15 || 1;

      // Draw Grid & Axes
      ctx.strokeStyle = '#122016';
      ctx.lineWidth = 1;

      for (let i = 0; i <= 4; i++) {
        const y = pad.top + (h - pad.top - pad.bottom) * (i / 4);
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(w - pad.right, y);
        ctx.stroke();

        ctx.fillStyle = '#506556';
        ctx.font = '10px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${Math.round(maxTPS * (1 - i / 4))} t/s`, pad.left - 6, y + 3);
      }

      for (let i = 0; i <= 4; i++) {
        const x = pad.left + (w - pad.left - pad.right) * (i / 4);
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, h - pad.bottom);
        ctx.stroke();

        ctx.fillStyle = '#506556';
        ctx.font = '10px monospace';
        ctx.textAlign = 'center';
        const ttVal = (maxTTFT * (i / 4)).toFixed(1);
        ctx.fillText(`${ttVal}s`, x, h - pad.bottom + 15);
      }

      // Axis labels
      ctx.fillStyle = '#8ba391';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('TTFT (Latency, lower is better) →', pad.left + (w - pad.left - pad.right) / 2, h - 6);

      // Plot Points
      const points = valid.map(r => {
        const x = pad.left + (r.avg_ttft / maxTTFT) * (w - pad.left - pad.right);
        const y = pad.top + (1 - r.avg_tps / maxTPS) * (h - pad.top - pad.bottom);
        return { x, y, r };
      });

      points.forEach(p => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
        ctx.fillStyle = '#4ade80';
        ctx.shadowColor = '#4ade80';
        ctx.shadowBlur = 10;
        ctx.fill();
        ctx.shadowBlur = 0;
      });

      // Canvas Mousemove Hover Tooltip
      canvas.onmousemove = function(e) {
        const cRect = canvas.getBoundingClientRect();
        const mx = e.clientX - cRect.left;
        const my = e.clientY - cRect.top;
        let match = null;

        for (const p of points) {
          const dist = Math.hypot(p.x - mx, p.y - my);
          if (dist < 12) { match = p; break; }
        }

        if (match) {
          tooltip.style.opacity = '1';
          tooltip.style.left = `${match.x + 12}px`;
          tooltip.style.top = `${match.y - 20}px`;
          tooltip.innerHTML = `
            <div style="font-weight: 700; color: #fff; margin-bottom: 2px;">${match.r.model}</div>
            <div style="color: var(--neon-green);">TTFT: ${match.r.avg_ttft.toFixed(3)}s</div>
            <div style="color: var(--neon-green);">Speed: ${match.r.avg_tps.toFixed(1)} tok/s</div>
          `;
        } else {
          tooltip.style.opacity = '0';
        }
      };

      canvas.onmouseleave = function() {
        tooltip.style.opacity = '0';
      };

      canvas.onclick = function(e) {
        const cRect = canvas.getBoundingClientRect();
        const mx = e.clientX - cRect.left;
        const my = e.clientY - cRect.top;
        for (const p of points) {
          if (Math.hypot(p.x - mx, p.y - my) < 12) {
            openModal(p.r);
            break;
          }
        }
      };
    }

    setTimeout(initScatterPlot, 50);
    window.addEventListener('resize', initScatterPlot);

    // Keyboard Hotkeys
    window.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement !== document.getElementById('searchInput')) {
        e.preventDefault();
        document.getElementById('searchInput').focus();
      }
      if (e.key === 'Escape') {
        closeModalDirect();
        closeCompareModalDirect();
      }
    });

    function setViewMode(mode) {
      currentViewMode = mode;
      document.getElementById('tab-table-view').classList.toggle('active', mode === 'table');
      document.getElementById('tab-grid-view').classList.toggle('active', mode === 'grid');
      document.getElementById('tableViewSection').style.display = mode === 'table' ? 'block' : 'none';
      document.getElementById('gridViewSection').style.display = mode === 'grid' ? 'grid' : 'none';
      renderAll();
    }

    function setFilter(status, el) {
      currentStatusFilter = status;
      document.querySelectorAll('.filter-chips .chip').forEach(p => p.classList.remove('active'));
      el.classList.add('active');
      renderAll();
    }

    function handleSortSelect(val) {
      const [col, dir] = val.split('-');
      sortColumn = col;
      sortDirection = dir;
      renderAll();
    }

    function sortTable(col) {
      if (sortColumn === col) {
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        sortColumn = col;
        sortDirection = 'asc';
      }
      document.getElementById('sortSelect').value = `${sortColumn}-${sortDirection}`;
      renderAll();
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      document.getElementById('toastMsg').textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 2400);
    }

    function copyEndpoint() {
      navigator.clipboard.writeText(document.getElementById('ep-display').textContent).then(() => {
        showToast('Endpoint URL copied');
      });
    }

    function getFilteredData() {
      const query = (document.getElementById('searchInput').value || '').toLowerCase().trim();
      let filtered = results.filter(r => {
        if (currentStatusFilter !== 'ALL' && r.status !== currentStatusFilter) return false;
        if (query) {
          const matchModel = r.model.toLowerCase().includes(query);
          const matchPreview = (r.sample_preview || '').toLowerCase().includes(query);
          const matchErr = (r.errors || []).join(' ').toLowerCase().includes(query);
          if (!matchModel && !matchPreview && !matchErr) return false;
        }
        return true;
      });

      filtered.sort((a, b) => {
        let valA = a[sortColumn];
        let valB = b[sortColumn];
        if (valA === null || valA === undefined) valA = 999999;
        if (valB === null || valB === undefined) valB = 999999;
        if (typeof valA === 'string') {
          return sortDirection === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }
        return sortDirection === 'asc' ? valA - valB : valB - valA;
      });

      return filtered;
    }

    function renderAll() {
      const maxTTFT = Math.max(...results.map(r => r.avg_ttft || 0), 1);
      const maxTPS = Math.max(...results.map(r => r.avg_tps || 0), 1);
      const filtered = getFilteredData();

      // Update sort indicators on table
      ['model', 'status', 'avg_ttft', 'avg_total', 'avg_tps'].forEach(col => {
        const el = document.getElementById('sort-' + col);
        if (el) {
          el.textContent = sortColumn === col ? (sortDirection === 'asc' ? '▲' : '▼') : '';
        }
      });

      if (currentViewMode === 'table') {
        renderTable(filtered, maxTTFT, maxTPS);
      } else {
        renderGrid(filtered, maxTTFT, maxTPS);
      }
      updateCompareBar();
    }

    function renderTable(filtered, maxTTFT, maxTPS) {
      const tbody = document.getElementById('tableBody');
      tbody.innerHTML = '';

      if (filtered.length === 0) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td colspan="9" style="text-align: center; padding: 40px; color: var(--text-dim);">No matching models found</td>`;
        tbody.appendChild(tr);
        return;
      }

      filtered.forEach((r, idx) => {
        const tr = document.createElement('tr');
        const isChecked = selectedModels.has(r.model);

        let badgeClass = 'badge-fail';
        let badgeLabel = 'FAIL';
        if (r.status === 'PASS') {
          badgeClass = 'badge-pass';
          badgeLabel = 'PASS';
        } else if (r.status === 'PARTIAL') {
          badgeClass = 'badge-par';
          badgeLabel = 'PAR';
        } else if (r.status === 'SKIPPED') {
          badgeClass = 'badge-skip';
          badgeLabel = 'SKIP';
        }

        const ttftStr = r.avg_ttft !== null ? (r.avg_ttft < 1 ? `${Math.round(r.avg_ttft * 1000)} ms` : `${r.avg_ttft.toFixed(3)} s`) : '—';
        const totalStr = r.avg_total !== null ? `${r.avg_total.toFixed(3)} s` : '—';
        const tpsStr = r.avg_tps !== null ? `${r.avg_tps.toFixed(1)} tok/s` : '—';

        const ttftPct = r.avg_ttft ? Math.min(100, Math.round((r.avg_ttft / maxTTFT) * 100)) : 0;
        const tpsPct = r.avg_tps ? Math.min(100, Math.round((r.avg_tps / maxTPS) * 100)) : 0;

        let note = '—';
        if (r.status === 'PASS') {
          note = `"${r.sample_preview || ''}"`;
        } else if (r.status === 'SKIPPED') {
          note = 'Non-available fund / skipped';
        } else {
          note = (r.errors && r.errors.length) ? r.errors.join('; ') : 'Execution failed';
        }

        let rankHtml = `<span class="rank-badge rank-other">${idx + 1}</span>`;
        if (idx === 0) rankHtml = `<span class="rank-badge rank-1">1</span>`;
        else if (idx === 1) rankHtml = `<span class="rank-badge rank-2">2</span>`;
        else if (idx === 2) rankHtml = `<span class="rank-badge rank-3">3</span>`;

        tr.innerHTML = `
          <td><input type="checkbox" ${isChecked ? 'checked' : ''} onchange="toggleSelectModel('${r.model}', this.checked)" /></td>
          <td>${rankHtml}</td>
          <td>
            <span class="model-pill">
              ${r.model}
              <span class="copy-mini" onclick="copyTextToClipboard('${r.model}')" title="Copy model name">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>
              </span>
            </span>
          </td>
          <td><span class="badge ${badgeClass}"><span class="badge-dot"></span>${badgeLabel}</span></td>
          <td>
            <div class="meter-wrap">
              <span class="mono-cell">${ttftStr}</span>
              <div class="meter-bar-bg"><div class="meter-bar-fill-ttft" style="width: ${ttftPct}%;"></div></div>
            </div>
          </td>
          <td><span class="mono-cell">${totalStr}</span></td>
          <td>
            <div class="meter-wrap">
              <span class="mono-cell">${tpsStr}</span>
              <div class="meter-bar-bg"><div class="meter-bar-fill-speed" style="width: ${tpsPct}%;"></div></div>
            </div>
          </td>
          <td><div class="preview-truncate" title="${note.replace(/"/g, '&quot;')}">${note}</div></td>
          <td style="text-align: right;">
            <button class="btn" style="padding: 4px 10px; font-size: 11.5px;" onclick='openModal(${JSON.stringify(r).replace(/'/g, "&#39;")})'>Inspect</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    function renderGrid(filtered, maxTTFT, maxTPS) {
      const grid = document.getElementById('gridViewSection');
      grid.innerHTML = '';

      if (filtered.length === 0) {
        grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-dim);">No matching models found</div>`;
        return;
      }

      filtered.forEach(r => {
        const card = document.createElement('div');
        card.className = 'bento-model-card';
        const isChecked = selectedModels.has(r.model);

        let badgeClass = 'badge-fail';
        let badgeLabel = 'FAIL';
        if (r.status === 'PASS') {
          badgeClass = 'badge-pass';
          badgeLabel = 'PASS';
        } else if (r.status === 'PARTIAL') {
          badgeClass = 'badge-par';
          badgeLabel = 'PAR';
        } else if (r.status === 'SKIPPED') {
          badgeClass = 'badge-skip';
          badgeLabel = 'SKIP';
        }

        const ttftStr = r.avg_ttft !== null ? (r.avg_ttft < 1 ? `${Math.round(r.avg_ttft * 1000)} ms` : `${r.avg_ttft.toFixed(2)} s`) : '—';
        const totalStr = r.avg_total !== null ? `${r.avg_total.toFixed(2)} s` : '—';
        const tpsStr = r.avg_tps !== null ? `${r.avg_tps.toFixed(1)} t/s` : '—';

        let preview = r.sample_preview || (r.errors && r.errors.length ? r.errors.join('; ') : 'No output recorded');
        if (r.status === 'SKIPPED') preview = 'Model evaluation was skipped: Non-available fund.';

        card.innerHTML = `
          <div>
            <div class="card-head">
              <div style="display: flex; align-items: center; gap: 8px;">
                <input type="checkbox" ${isChecked ? 'checked' : ''} onchange="toggleSelectModel('${r.model}', this.checked)" />
                <span class="model-pill">${r.model}</span>
              </div>
              <span class="badge ${badgeClass}"><span class="badge-dot"></span>${badgeLabel}</span>
            </div>
            <div class="card-metrics-3">
              <div class="card-metric-col">
                <span class="card-metric-lbl">TTFT</span>
                <span class="card-metric-val" style="color: #38bdf8;">${ttftStr}</span>
              </div>
              <div class="card-metric-col">
                <span class="card-metric-lbl">Speed</span>
                <span class="card-metric-val" style="color: var(--neon-green);">${tpsStr}</span>
              </div>
              <div class="card-metric-col">
                <span class="card-metric-lbl">Total</span>
                <span class="card-metric-val">${totalStr}</span>
              </div>
            </div>
            <div class="card-preview-box">${preview}</div>
          </div>
          <div class="card-footer">
            <span style="font-size: 11px; color: var(--text-dim);">${r.success}/${r.runs} ok</span>
            <button class="btn" style="padding: 4px 10px; font-size: 12px;" onclick='openModal(${JSON.stringify(r).replace(/'/g, "&#39;")})'>Inspect</button>
          </div>
        `;
        grid.appendChild(card);
      });
    }

    function toggleSelectModel(model, isChecked) {
      if (isChecked) {
        selectedModels.add(model);
      } else {
        selectedModels.delete(model);
      }
      updateCompareBar();
    }

    function toggleSelectAll(box) {
      const filtered = getFilteredData();
      if (box.checked) {
        filtered.forEach(r => selectedModels.add(r.model));
      } else {
        selectedModels.clear();
      }
      renderAll();
    }

    function clearSelection() {
      selectedModels.clear();
      renderAll();
    }

    function updateCompareBar() {
      const bar = document.getElementById('compareBar');
      const count = selectedModels.size;
      document.getElementById('compareCountText').textContent = `${count} model${count === 1 ? '' : 's'} selected`;
      if (count >= 1) {
        bar.classList.add('show');
      } else {
        bar.classList.remove('show');
      }
    }

    function openComparisonModal() {
      const selectedList = results.filter(r => selectedModels.has(r.model));
      if (!selectedList.length) return;

      const grid = document.getElementById('compareGrid');
      grid.innerHTML = '';

      const validTTFT = selectedList.filter(r => r.avg_ttft !== null);
      const minTTFT = validTTFT.length ? Math.min(...validTTFT.map(r => r.avg_ttft)) : null;
      const validTPS = selectedList.filter(r => r.avg_tps !== null);
      const maxTPS = validTPS.length ? Math.max(...validTPS.map(r => r.avg_tps)) : null;

      selectedList.forEach(r => {
        const col = document.createElement('div');
        col.className = 'compare-col';

        const isFastestTTFT = minTTFT !== null && r.avg_ttft === minTTFT;
        const isFastestTPS = maxTPS !== null && r.avg_tps === maxTPS;

        const ttftStr = r.avg_ttft !== null ? (r.avg_ttft < 1 ? `${Math.round(r.avg_ttft * 1000)} ms` : `${r.avg_ttft.toFixed(3)} s`) : '—';
        const totalStr = r.avg_total !== null ? `${r.avg_total.toFixed(3)} s` : '—';
        const tpsStr = r.avg_tps !== null ? `${r.avg_tps.toFixed(1)} tok/s` : '—';

        let preview = r.sample_preview || (r.errors && r.errors.length ? r.errors.join('\n') : 'No output recorded');

        col.innerHTML = `
          <div class="compare-col-header">
            <div>${r.model}</div>
            <div style="font-size: 11px; font-weight: 500; color: ${r.status === 'PASS' ? 'var(--neon-green)' : 'var(--rose)'}; margin-top: 2px;">
              ${r.status} (${r.success}/${r.runs})
            </div>
          </div>
          <div>
            <div style="font-size: 11px; color: var(--text-dim); text-transform: uppercase;">TTFT</div>
            <div style="font-size: 16px; font-weight: 700; font-family: var(--font-mono); color: ${isFastestTTFT ? 'var(--neon-green)' : '#38bdf8'};">
              ${ttftStr} ${isFastestTTFT ? '⚡ Best' : ''}
            </div>
          </div>
          <div>
            <div style="font-size: 11px; color: var(--text-dim); text-transform: uppercase;">Speed</div>
            <div style="font-size: 16px; font-weight: 700; font-family: var(--font-mono); color: ${isFastestTPS ? 'var(--neon-green)' : 'var(--text)'};">
              ${tpsStr} ${isFastestTPS ? '🚀 Peak' : ''}
            </div>
          </div>
          <div>
            <div style="font-size: 11px; color: var(--text-dim); text-transform: uppercase;">Total Duration</div>
            <div style="font-size: 14px; font-weight: 600; font-family: var(--font-mono);">${totalStr}</div>
          </div>
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <span style="font-size: 11px; color: var(--text-dim); text-transform: uppercase;">Response Output</span>
              <button class="btn" style="padding: 2px 8px; font-size: 11px;" onclick="copyTextToClipboard('${encodeURIComponent(preview)}')">Copy</button>
            </div>
            <div class="code-box" style="max-height: 200px;">${preview.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>
          </div>
        `;
        grid.appendChild(col);
      });

      document.getElementById('compareModalOverlay').classList.add('open');
    }

    function closeCompareModalDirect() {
      document.getElementById('compareModalOverlay').classList.remove('open');
    }
    function closeCompareModal(e) {
      if (e.target.id === 'compareModalOverlay') closeCompareModalDirect();
    }

    function openModal(r) {
      document.getElementById('modalTitle').textContent = r.model;
      document.getElementById('modalSubtitle').textContent = `Endpoint: ${DATA.endpoint || '{ENDPOINT}'}`;

      const ttftStr = r.avg_ttft !== null ? (r.avg_ttft < 1 ? `${Math.round(r.avg_ttft * 1000)} ms` : `${r.avg_ttft.toFixed(3)} s`) : '—';
      const totalStr = r.avg_total !== null ? `${r.avg_total.toFixed(3)} s` : '—';
      const tpsStr = r.avg_tps !== null ? `${r.avg_tps.toFixed(1)} tok/s` : '—';

      let previewContent = r.sample_preview || (r.errors && r.errors.length ? r.errors.join('\n') : 'No output recorded.');
      if (r.status === 'SKIPPED') {
        previewContent = 'Model evaluation was skipped: Non-available fund or quota limit.';
      }

      document.getElementById('modalBody').innerHTML = `
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;">
          <div style="background: #0d1510; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 10px 12px;">
            <div style="font-size: 11px; color: var(--text-dim); font-weight: 600; text-transform: uppercase;">Status</div>
            <div style="font-size: 15px; font-weight: 700; font-family: var(--font-mono); margin-top: 2px;">${r.status} (${r.success}/${r.runs})</div>
          </div>
          <div style="background: #0d1510; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 10px 12px;">
            <div style="font-size: 11px; color: var(--text-dim); font-weight: 600; text-transform: uppercase;">TTFT</div>
            <div style="font-size: 15px; font-weight: 700; font-family: var(--font-mono); color: #38bdf8; margin-top: 2px;">${ttftStr}</div>
          </div>
          <div style="background: #0d1510; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 10px 12px;">
            <div style="font-size: 11px; color: var(--text-dim); font-weight: 600; text-transform: uppercase;">Speed</div>
            <div style="font-size: 15px; font-weight: 700; font-family: var(--font-mono); color: var(--neon-green); margin-top: 2px;">${tpsStr}</div>
          </div>
          <div style="background: #0d1510; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 10px 12px;">
            <div style="font-size: 11px; color: var(--text-dim); font-weight: 600; text-transform: uppercase;">Total Time</div>
            <div style="font-size: 15px; font-weight: 700; font-family: var(--font-mono); margin-top: 2px;">${totalStr}</div>
          </div>
        </div>

        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Prompt Response / Diagnostics</span>
            <button class="btn" style="padding: 3px 9px; font-size: 11.5px;" onclick="copyTextToClipboard('${encodeURIComponent(previewContent)}')">Copy Response</button>
          </div>
          <div class="code-box">${previewContent.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>
        </div>

        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 12px; font-weight: 600; color: var(--text-muted);">Raw Evaluation JSON</span>
            <button class="btn" style="padding: 3px 9px; font-size: 11.5px;" onclick="copyTextToClipboard('${encodeURIComponent(JSON.stringify(r, null, 2))}')">Copy JSON</button>
          </div>
          <div class="code-box" style="font-size: 11.5px; max-height: 160px; color: #8ba391;">${JSON.stringify(r, null, 2).replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>
        </div>
      `;
      document.getElementById('modalOverlay').classList.add('open');
    }

    function copyTextToClipboard(encoded) {
      const text = decodeURIComponent(encoded);
      navigator.clipboard.writeText(text).then(() => showToast('Copied to clipboard'));
    }

    function closeModalDirect() {
      document.getElementById('modalOverlay').classList.remove('open');
    }

    function closeModal(e) {
      if (e.target.id === 'modalOverlay') closeModalDirect();
    }

    function copyMarkdown() {
      let md = "# LLM Benchmark Results\n\n";
      md += `**Endpoint**: \`${DATA.endpoint || '{ENDPOINT}'}\`\n\n`;
      md += "| # | Model ID | Status | TTFT | Total Time | Speed | Output Preview |\n|---|---|---|---|---|---|---|\n";
      results.forEach((r, idx) => {
        const ttftStr = r.avg_ttft ? (r.avg_ttft < 1 ? `${Math.round(r.avg_ttft * 1000)} ms` : `${r.avg_ttft.toFixed(3)} s`) : '—';
        const totalStr = r.avg_total ? `${r.avg_total.toFixed(3)} s` : '—';
        const tpsStr = r.avg_tps ? `${r.avg_tps.toFixed(1)} tok/s` : '—';
        const preview = (r.sample_preview || (r.errors || []).join(' ')).replace(/\|/g, '\\|').replace(/\n/g, ' ');
        md += `| ${idx + 1} | \`${r.model}\` | ${r.status} | ${ttftStr} | ${totalStr} | ${tpsStr} | ${preview.slice(0, 50)} |\n`;
      });
      navigator.clipboard.writeText(md).then(() => showToast('Markdown table copied'));
    }

    function copySummaryCard() {
      let card = `⚡ LLMtest Benchmark Summary (${DATA.endpoint || '{ENDPOINT}'})\n`;
      card += `• Total Models : ${total}\n`;
      card += `• Active Passed: ${passCount}/${activeTotal} (${passPct}%)\n`;
      if (document.getElementById('kpi-ttft-model').textContent !== '—') {
        card += `• Fastest TTFT : ${document.getElementById('kpi-ttft').textContent} (${document.getElementById('kpi-ttft-model').textContent})\n`;
      }
      if (document.getElementById('kpi-speed-model').textContent !== '—') {
        card += `• Peak Speed   : ${document.getElementById('kpi-speed').textContent} (${document.getElementById('kpi-speed-model').textContent})\n`;
      }
      navigator.clipboard.writeText(card).then(() => showToast('Summary card copied'));
    }

    function downloadCSV() {
      let csv = "Model ID,Status,Success Runs,Total Runs,Avg TTFT (s),Avg Total Time (s),Avg Speed (tok/s),Preview / Note\n";
      results.forEach(r => {
        const note = (r.sample_preview || (r.errors || []).join(' ')).replace(/"/g, '""');
        csv += `"${r.model}","${r.status}",${r.success},${r.runs},${r.avg_ttft || ''},${r.avg_total || ''},${r.avg_tps || ''},"${note}"\n`;
      });
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'benchmark_report.csv';
      a.click();
      showToast('Exported benchmark_report.csv');
    }

    function downloadJSON() {
      const blob = new Blob([JSON.stringify(DATA, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'benchmark_report.json';
      a.click();
      showToast('Exported benchmark_report.json');
    }

    renderAll();
  </script>
</body>
</html>
"""


def export_html_report(results, filepath: str, endpoint: str):
    """
    Generates a standalone, interactive, dark-mode Web UI dashboard report.
    Crafted with sleek modern glassmorphism, visual scatter plot, speed leaderboard,
    side-by-side comparison drawer, and comprehensive search & filtering.
    Zero external dependencies — works 100% offline.
    """
    raw_data_json = json.dumps({
        "endpoint": endpoint,
        "tested_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "results": results
    }, ensure_ascii=False)

    html_content = HTML_REPORT_TEMPLATE.replace("{ENDPOINT}", endpoint).replace("{DATA_JSON}", raw_data_json)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    abs_path = os.path.abspath(filepath)
    file_uri = f"file:///{abs_path.replace(os.sep, '/')}"
    print(f" {CLR_GREEN}✔{CLR_RESET} Interactive Web UI report : {CLR_CYAN}{file_uri}{CLR_RESET} {CLR_GRAY}(Ctrl+Click to view){CLR_RESET}")


BANNER = f"""{CLR_CYAN}┌─────────────────────────────────────────────────────────────┐
│  {CLR_BOLD}⚡ llmtest — LLM Speed & Latency Benchmark{CLR_RESET}{CLR_CYAN}                │
│  {CLR_GRAY}Fast, zero-dependency OpenAI-compatible evaluator         {CLR_CYAN}│
└─────────────────────────────────────────────────────────────┘{CLR_RESET}"""

def is_pipx_environment():
    """Detects if running inside a pipx-managed environment."""
    prefix_lower = sys.prefix.lower()
    exec_lower = sys.executable.lower()
    return "pipx" in prefix_lower or "pipx" in exec_lower

def handle_update():
    """Updates llmtest to the latest version from GitHub across pipx, pip, and pip3."""
    print(f"\n{CLR_BOLD}⚡ Updating llmtest to the latest version from GitHub...{CLR_RESET}")
    repo_url = "git+https://github.com/mijanlab/LLMtest.git"
    success = False
    error_msgs = []

    # 1. If running under pipx or pipx is present
    if is_pipx_environment() and shutil.which("pipx"):
        cmd = ["pipx", "install", "--force", repo_url]
        try:
            res = subprocess.run(cmd)
            if res.returncode == 0:
                success = True
        except Exception as e:
            error_msgs.append(f"pipx error: {e}")

    # 2. Try sys.executable -m pip if not succeeded
    if not success:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", repo_url]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                success = True
            else:
                error_msgs.append(f"pip error: {res.stderr.strip()}")
        except Exception as e:
            error_msgs.append(f"pip error: {e}")

    # 3. Fallback to global pip3 / pip
    if not success:
        for bin_name in ["pip3", "pip"]:
            if shutil.which(bin_name):
                cmd = [bin_name, "install", "--upgrade", "--no-cache-dir", repo_url]
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True)
                    if res.returncode == 0:
                        success = True
                        break
                    else:
                        error_msgs.append(f"{bin_name} error: {res.stderr.strip()}")
                except Exception as e:
                    error_msgs.append(f"{bin_name} error: {e}")

    if success:
        print(f" {CLR_GREEN}✔ Successfully updated llmtest to the latest version from GitHub!{CLR_RESET}\n")
    else:
        print(f" {CLR_RED}✖ Update failed. You can manually run:{CLR_RESET}")
        print(f"   {CLR_CYAN}pip install --upgrade --no-cache-dir {repo_url}{CLR_RESET}\n")
        if error_msgs:
            print(f" {CLR_GRAY}Diagnostic info:{CLR_RESET}")
            for msg in error_msgs:
                print(f"   {CLR_GRAY}{msg}{CLR_RESET}")
    sys.exit(0)

def handle_uninstall():
    """Uninstalls llmtest from the system environment."""
    print(f"\n{CLR_BOLD}🗑️  Uninstalling llmtest...{CLR_RESET}")
    success = False

    if is_pipx_environment() and shutil.which("pipx"):
        cmd = ["pipx", "uninstall", "llmtest"]
        try:
            res = subprocess.run(cmd)
            if res.returncode == 0:
                success = True
        except Exception:
            pass

    if not success:
        cmd = [sys.executable, "-m", "pip", "uninstall", "-y", "llmtest"]
        try:
            res = subprocess.run(cmd)
            if res.returncode == 0:
                success = True
        except Exception:
            pass

    if not success:
        for bin_name in ["pip3", "pip"]:
            if shutil.which(bin_name):
                cmd = [bin_name, "uninstall", "-y", "llmtest"]
                try:
                    res = subprocess.run(cmd)
                    if res.returncode == 0:
                        success = True
                        break
                except Exception:
                    pass

    if success:
        print(f" {CLR_GREEN}✔ llmtest has been completely uninstalled.{CLR_RESET}\n")
    else:
        print(f" {CLR_RED}✖ Uninstall failed. You can run manually:{CLR_RESET}")
        print(f"   {CLR_CYAN}pip uninstall -y llmtest{CLR_RESET}\n")
    sys.exit(0)

def prompt_wizard():
    """Interactive CLI wizard when user runs `llmtest` with zero arguments."""
    print(f"\n{CLR_CYAN}⚡ Interactive Setup Wizard{CLR_RESET}")
    print(f"{CLR_GRAY}Follow the steps below to configure your benchmark run:{CLR_RESET}\n")

    # Step 1: Endpoint
    while True:
        try:
            ep_input = input(f"{CLR_BOLD}1. API Endpoint URL{CLR_RESET} (e.g. https://lab.proclfy.link/v1): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

        if not ep_input:
            print(f"   {CLR_RED}✖ Endpoint URL cannot be empty.{CLR_RESET}")
            continue
        if ep_input.lower() in ("update", "--update"):
            handle_update()
        if ep_input.lower() in ("uninstall", "--uninstall"):
            handle_uninstall()
        if ep_input.lower() in ("exit", "quit", "q"):
            print("Exiting.")
            sys.exit(0)
        endpoint = ep_input
        break

    # Step 2: API Key
    try:
        key_input = input(f"\n{CLR_BOLD}2. API Key{CLR_RESET} [press Enter if none]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        sys.exit(0)
    api_key = key_input

    # Step 3: Filter
    try:
        filter_input = input(f"\n{CLR_BOLD}3. Model Filter{CLR_RESET} [e.g. 'free', 'flash', or Enter for all]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        sys.exit(0)
    model_filter = filter_input

    # Step 4: Concurrency
    try:
        conc_input = input(f"\n{CLR_BOLD}4. Concurrency{CLR_RESET} [default 3 workers]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        sys.exit(0)
    concurrency = 3
    if conc_input:
        try:
            concurrency = max(1, int(conc_input))
        except ValueError:
            concurrency = 3

    print()
    return endpoint, api_key, model_filter, concurrency

def handle_render_from_json(json_path: str, args):
    """Renders HTML, Markdown, and CSV reports from an existing benchmark JSON file."""
    if not os.path.exists(json_path):
        print(f"{CLR_RED}✖ JSON report file not found: {json_path}{CLR_RESET}")
        sys.exit(1)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"{CLR_RED}✖ Failed to parse JSON report {json_path}: {e}{CLR_RESET}")
        sys.exit(1)

    endpoint = data.get("endpoint", "Unknown Endpoint")
    results = data.get("results", [])

    print(f"\n{CLR_BOLD}📂 Rendering reports from: {CLR_CYAN}{os.path.abspath(json_path)}{CLR_RESET}")
    print(f" {CLR_GRAY}• Endpoint: {endpoint}{CLR_RESET}")
    print(f" {CLR_GRAY}• Models  : {len(results)}{CLR_RESET}\n")

    # Display table & card
    print_table(results)
    print_summary_card(results, 0.0)

    if not args.no_report:
        print(f"{CLR_BOLD}📁 Exported Reports:{CLR_RESET}")
        if args.output_html:
            export_html_report(results, args.output_html, endpoint)
        if args.output_md:
            export_markdown_report(results, args.output_md, endpoint)
        if args.output_csv:
            export_csv_report(results, args.output_csv, endpoint)

    if args.open and args.output_html:
        html_uri = f"file:///{os.path.abspath(args.output_html).replace(os.sep, '/')}"
        webbrowser.open(html_uri)

def main():
    print(BANNER)

    parser = argparse.ArgumentParser(
        prog="llmtest",
        description="⚡ Fast CLI tool to discover & benchmark all LLM models for any OpenAI-compatible endpoint.",
        usage="%(prog)s [endpoint | update | uninstall] [key] [filter] [options]"
    )
    # Positional shortcuts (for ultra-short command lines)
    parser.add_argument("pos_endpoint", nargs="?", default="", help="API endpoint URL, JSON report path, or 'update' / 'uninstall'")
    parser.add_argument("pos_key", nargs="?", default="", help="API Key (optional)")
    parser.add_argument("pos_filter", nargs="?", default="", help="Model filter keyword (e.g. 'free', 'flash')")

    # Version flag
    parser.add_argument("--version", "-v", action="version", version="llmtest 1.0.2", help="Show version number and exit")

    # Management flags
    parser.add_argument("--update", action="store_true", help="Update llmtest to the latest version from GitHub")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall llmtest from your Python environment")

    # Report rendering from JSON
    parser.add_argument("--report", "--render", type=str, default="", help="Render interactive HTML/MD/CSV report from an existing benchmark JSON file")
    parser.add_argument("--no-report", action="store_true", help="Do not write report files to disk")

    # Named options
    parser.add_argument("--endpoint", "-e", type=str, default="", help="API endpoint URL")
    parser.add_argument("--key", "-k", type=str, default="", help="API Key (Authorization: Bearer <key>)")
    parser.add_argument("--filter", "-f", type=str, default="", help="Filter model IDs by substring")
    parser.add_argument("--limit", "-l", type=int, default=0, help="Limit number of models to test (0 = all)")
    parser.add_argument("--runs", "-r", type=int, default=1, help="Runs per model (default: 1)")
    parser.add_argument("--concurrency", "-c", type=int, default=3, help="Concurrent workers (default: 3)")
    parser.add_argument("--prompt", "-p", type=str, default="Say hello and describe your purpose in one brief sentence.", help="Evaluation prompt")
    parser.add_argument("--system", "-s", type=str, default="You are a helpful assistant.", help="System prompt")
    parser.add_argument("--max-tokens", type=int, default=60, help="Max tokens per request (default: 60)")
    parser.add_argument("--timeout", type=int, default=35, help="Request timeout in seconds (default: 35s)")
    parser.add_argument("--output-html", "--html", type=str, default="benchmark_report.html", help="Interactive HTML report output path")
    parser.add_argument("--output-md", type=str, default="benchmark_report.md", help="Markdown report output path")
    parser.add_argument("--output-csv", "--csv", type=str, default="benchmark_report.csv", help="CSV report output path")
    parser.add_argument("--output-json", type=str, default="benchmark_report.json", help="JSON report output path")
    parser.add_argument("--open", action="store_true", help="Automatically open interactive Web UI report in browser")

    args = parser.parse_args()

    if args.update:
        handle_update()
    if args.uninstall:
        handle_uninstall()

    # Check if rendering existing report from JSON
    if args.report:
        handle_render_from_json(args.report, args)
        return
    if args.pos_endpoint and args.pos_endpoint.endswith(".json") and os.path.exists(args.pos_endpoint):
        handle_render_from_json(args.pos_endpoint, args)
        return

    endpoint = args.pos_endpoint or args.endpoint
    key = args.pos_key or args.key
    model_filter = args.pos_filter or args.filter
    concurrency = args.concurrency
    is_interactive = not endpoint

    # If invoked with no endpoint argument, launch the interactive wizard
    if not endpoint:
        endpoint, key, model_filter, concurrency = prompt_wizard()

    if not endpoint:
        print(f"{CLR_RED}✖ No endpoint specified. Exiting.{CLR_RESET}")
        return

    models_url, chat_url = normalize_urls(endpoint)
    masked_key = (key[:6] + "..." + key[-4:]) if len(key) > 12 else ("(none)" if not key else "••••••••")

    print(f"{CLR_BOLD}Connecting to endpoint:{CLR_RESET} {CLR_CYAN}{endpoint}{CLR_RESET}")
    print(f" {CLR_GRAY}• Models URL : {models_url}{CLR_RESET}")
    print(f" {CLR_GRAY}• Chat URL   : {chat_url}{CLR_RESET}")
    print(f" {CLR_GRAY}• API Key    : {masked_key}{CLR_RESET}\n")

    # 1. Discover models
    all_models = fetch_available_models(models_url, key, timeout=args.timeout)
    if not all_models:
        print(f"{CLR_RED}✖ No models discovered from {models_url}. Check endpoint URL and API Key.{CLR_RESET}")
        return

    print(f" {CLR_GREEN}✔ Discovered {len(all_models)} total models.{CLR_RESET}")

    # 2. Filter models
    filtered_models = all_models
    if model_filter:
        if model_filter.lower() == "free":
            filtered_models = [m for m in all_models if m.get("is_free") or ":free" in m.get("id", "")]
            print(f" {CLR_CYAN}✔ Filtered to {len(filtered_models)} free models.{CLR_RESET}")
        else:
            filtered_models = [m for m in all_models if model_filter.lower() in m.get("id", "").lower()]
            print(f" {CLR_CYAN}✔ Filtered to {len(filtered_models)} models matching '{model_filter}'.{CLR_RESET}")

    if args.limit and args.limit > 0:
        filtered_models = filtered_models[:args.limit]
        print(f" {CLR_GRAY}• Limited to first {len(filtered_models)} models.{CLR_RESET}")

    if not filtered_models:
        print(f"{CLR_YELLOW}⚠ No models match the filter '{model_filter}'.{CLR_RESET}")
        return

    total_models = len(filtered_models)
    print(f"\n{CLR_BOLD}🚀 Starting benchmark ({total_models} models | Concurrency: {concurrency} | Runs: {args.runs})...{CLR_RESET}\n")

    results = []
    def test_worker(m_info):
        m_id = m_info["id"]
        return benchmark_model(
            chat_url=chat_url,
            model_id=m_id,
            api_key=key,
            prompt=args.prompt,
            system_prompt=args.system,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            runs=args.runs
        )

    start_bench = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        future_map = {executor.submit(test_worker, m): m for m in filtered_models}
        for future in concurrent.futures.as_completed(future_map):
            m_info = future_map[future]
            try:
                r = future.result()
                results.append(r)
                status_badge = f"{CLR_GREEN}🟢 PASS{CLR_RESET}" if r["status"] == "PASS" else (f"{CLR_YELLOW}🟡 PAR {CLR_RESET}" if r["status"] == "PARTIAL" else f"{CLR_RED}🔴 FAIL{CLR_RESET}")
                ttft_dsp = f"{r['avg_ttft']*1000:.0f}ms" if r['avg_ttft'] and r['avg_ttft'] < 1 else (f"{r['avg_ttft']:.2f}s" if r['avg_ttft'] else "—")
                tps_dsp = f"{r['avg_tps']:.1f} tok/s" if r['avg_tps'] else "—"
                model_dsp = (r['model'][:26] + "...") if len(r['model']) > 29 else r['model']
                print(f" [{len(results):>2}/{total_models}] {status_badge}  {model_dsp:<29} │ TTFT: {ttft_dsp:<7} │ Speed: {tps_dsp:<10}")
            except Exception as exc:
                print(f" {CLR_RED}✖ Error testing {m_info['id']}: {exc}{CLR_RESET}")

    total_wall_time = time.perf_counter() - start_bench

    # Sort results: PASS first, then by fastest avg_ttft
    results.sort(key=lambda x: (0 if x["status"] == "PASS" else (1 if x["status"] == "PARTIAL" else 2), x["avg_ttft"] or 999))

    # Display clean table
    print_table(results)

    # Display executive summary card
    print_summary_card(results, total_wall_time)

    # Export reports
    if not args.no_report:
        print(f"{CLR_BOLD}📁 Exported Reports:{CLR_RESET}")
        if args.output_html:
            export_html_report(results, args.output_html, endpoint)
        if args.output_md:
            export_markdown_report(results, args.output_md, endpoint)
        if args.output_csv:
            export_csv_report(results, args.output_csv, endpoint)
        if args.output_json:
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump({"endpoint": endpoint, "tested_at": time.time(), "results": results}, f, indent=2)
            print(f" {CLR_GREEN}✔{CLR_RESET} JSON report     : {CLR_CYAN}{os.path.abspath(args.output_json)}{CLR_RESET}")

    # Auto-open in browser if requested
    if args.open and args.output_html and not args.no_report:
        html_uri = f"file:///{os.path.abspath(args.output_html).replace(os.sep, '/')}"
        webbrowser.open(html_uri)

    # Helpful tip for one-liner syntax
    print(f"\n {CLR_GRAY}💡 Tip: You can run directly in 1 line next time:{CLR_RESET}")
    clean_key = "<your_api_key>" if key else ""
    filt_arg = f" {model_filter}" if model_filter else ""
    print(f"    {CLR_CYAN}llmtest {endpoint} {clean_key}{filt_arg}{CLR_RESET}\n")

if __name__ == "__main__":
    main()
