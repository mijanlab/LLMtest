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
import shutil
import argparse
import subprocess
import statistics
import concurrent.futures
import webbrowser
from urllib.parse import urlparse

# Reconfigure stdout/stderr to UTF-8 on Windows consoles safely
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

BANNER = f"""{CLR_CYAN}┌─────────────────────────────────────────────────────────────┐
│  {CLR_BOLD}⚡ llmtest — LLM Speed & Latency Benchmark{CLR_RESET}{CLR_CYAN}                │
│  {CLR_GRAY}Fast, zero-dependency OpenAI-compatible evaluator         {CLR_CYAN}│
└─────────────────────────────────────────────────────────────┘{CLR_RESET}"""

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
    passed_count = sum(1 for r in results if r['status'] == 'PASS')
    skipped_count = sum(1 for r in results if r['status'] == 'SKIPPED')
    failed_count = sum(1 for r in results if r['status'] == 'FAIL')

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
        if r['status'] == "PASS":
            status_badge = f"🟢 {r['success']}/{r['runs']} OK"
        elif r['status'] == "PARTIAL":
            status_badge = f"🟡 {r['success']}/{r['runs']} Partial"
        elif r['status'] == "SKIPPED":
            status_badge = f"⚪ Skipped"
        else:
            status_badge = f"🔴 0/{r['runs']} FAIL"

        ttft_str = f"{r['avg_ttft']*1000:.0f} ms" if r['avg_ttft'] and r['avg_ttft'] < 1 else (f"{r['avg_ttft']:.3f} s" if r['avg_ttft'] else "—")
        total_str = f"{r['avg_total']:.3f} s" if r['avg_total'] else "—"
        tps_str = f"{r['avg_tps']:.1f} tok/s" if r['avg_tps'] else "—"
        
        if r['status'] == "PASS":
            preview = (r['sample_preview'] or "").replace("|", "\\|").replace("\n", " ")
            note = f'"{preview}"'
        elif r['status'] == "SKIPPED":
            note = "Non-available fund (skipped)"
        else:
            note = ("; ".join(r['errors']) or "Failed").replace("|", "\\|").replace("\n", " ")

        lines.append(f"| {i} | `{r['model']}` | {status_badge} | {ttft_str} | {total_str} | {tps_str} | {note[:65]} |")

    lines.append("")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f" {CLR_GREEN}✔{CLR_RESET} Markdown report : {CLR_CYAN}{os.path.abspath(filepath)}{CLR_RESET}")

def export_html_report(results, filepath: str, endpoint: str):
    """
    Generates a standalone, interactive, dark-mode Web UI dashboard report.
    Can be opened directly in any browser without requiring a server.
    """
    raw_data_json = json.dumps({
        "endpoint": endpoint,
        "tested_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "results": results
    }, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LLM Benchmark Report — {endpoint}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #09090b;
      --card: #121215;
      --card-hover: #18181b;
      --border: #27272a;
      --text: #f4f4f5;
      --text-muted: #a1a1aa;
      --accent: #38bdf8;
      --green: #22c55e;
      --yellow: #eab308;
      --red: #ef4444;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }}
    body {{
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--font);
      line-height: 1.5;
      padding: 32px 24px;
      min-height: 100vh;
    }}
    .container {{ max-width: 1280px; margin: 0 auto; }}
    
    /* Header */
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 28px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
      gap: 16px;
    }}
    .header-title h1 {{
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .header-title p {{
      color: var(--text-muted);
      font-size: 14px;
      margin-top: 4px;
    }}
    .endpoint-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      background: #18181b;
      border: 1px solid var(--border);
      border-radius: 6px;
      font-family: var(--mono);
      font-size: 13px;
      color: var(--accent);
    }}
    .actions {{ display: flex; gap: 8px; }}
    .btn {{
      background: #27272a;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 8px 14px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }}
    .btn:hover {{ background: #3f3f46; border-color: #52525b; }}

    /* KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }}
    .kpi-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 18px 20px;
    }}
    .kpi-label {{
      font-size: 13px;
      color: var(--text-muted);
      font-weight: 500;
      margin-bottom: 6px;
    }}
    .kpi-value {{
      font-size: 26px;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    .kpi-sub {{
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 4px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    /* Filters Bar */
    .controls {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .search-box {{
      position: relative;
      flex: 1;
      max-width: 360px;
    }}
    .search-box input {{
      width: 100%;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 12px 8px 34px;
      color: var(--text);
      font-size: 14px;
      outline: none;
      transition: border-color 0.15s ease;
    }}
    .search-box input:focus {{ border-color: var(--accent); }}
    .search-icon {{
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 14px;
    }}
    .filter-pills {{ display: flex; gap: 6px; }}
    .pill {{
      background: var(--card);
      border: 1px solid var(--border);
      color: var(--text-muted);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 13px;
      cursor: pointer;
      font-weight: 500;
      transition: all 0.15s ease;
    }}
    .pill.active, .pill:hover {{
      background: #27272a;
      color: var(--text);
      border-color: #52525b;
    }}

    /* Table */
    .table-wrap {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 14px;
    }}
    th {{
      background: #18181b;
      padding: 12px 16px;
      font-weight: 600;
      color: var(--text-muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}
    th:hover {{ color: var(--text); }}
    th.sorted-asc::after {{ content: " ↑"; color: var(--accent); }}
    th.sorted-desc::after {{ content: " ↓"; color: var(--accent); }}
    td {{
      padding: 14px 16px;
      border-bottom: 1px solid #1f1f23;
      vertical-align: middle;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr.clickable {{ cursor: pointer; transition: background 0.15s ease; }}
    tr.clickable:hover {{ background: var(--card-hover); }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 600;
      font-family: var(--mono);
    }}
    .badge-pass {{ background: rgba(34, 197, 94, 0.12); color: var(--green); border: 1px solid rgba(34, 197, 94, 0.25); }}
    .badge-par {{ background: rgba(234, 179, 8, 0.12); color: var(--yellow); border: 1px solid rgba(234, 179, 8, 0.25); }}
    .badge-skip {{ background: rgba(161, 161, 170, 0.12); color: #a1a1aa; border: 1px solid rgba(161, 161, 170, 0.25); }}
    .badge-fail {{ background: rgba(239, 68, 68, 0.12); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.25); }}

    .note-banner {{
      background: rgba(39, 39, 42, 0.6);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 20px;
      font-size: 13.5px;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .model-name {{
      font-family: var(--mono);
      font-weight: 600;
      color: var(--text);
      font-size: 13.5px;
    }}
    .latency-bar-wrap {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-family: var(--mono);
      font-size: 13px;
    }}
    .bar {{
      height: 6px;
      background: #27272a;
      border-radius: 3px;
      overflow: hidden;
      width: 60px;
    }}
    .bar-fill-ttft {{ height: 100%; background: var(--accent); border-radius: 3px; }}
    .bar-fill-speed {{ height: 100%; background: var(--green); border-radius: 3px; }}
    .preview-text {{
      color: var(--text-muted);
      font-size: 13px;
      max-width: 380px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    /* Modal */
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      padding: 20px;
    }}
    .modal-backdrop.open {{ display: flex; }}
    .modal {{
      background: #121215;
      border: 1px solid var(--border);
      border-radius: 12px;
      width: 100%;
      max-width: 680px;
      max-height: 85vh;
      overflow-y: auto;
      padding: 24px;
      box-shadow: 0 20px 40px rgba(0,0,0,0.5);
    }}
    .modal-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--border);
    }}
    .modal-title {{ font-size: 18px; font-weight: 700; }}
    .modal-close {{
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 20px;
      cursor: pointer;
    }}
    .modal-close:hover {{ color: var(--text); }}
    .detail-row {{
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px solid #1f1f23;
      font-size: 13.5px;
    }}
    .detail-label {{ color: var(--text-muted); font-weight: 500; }}
    .detail-val {{ font-family: var(--mono); font-weight: 600; }}
    .preview-box {{
      background: #09090b;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      margin-top: 14px;
      font-family: var(--mono);
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-word;
      color: #e4e4e7;
      max-height: 240px;
      overflow-y: auto;
    }}

    .footer {{
      margin-top: 36px;
      text-align: center;
      color: var(--text-muted);
      font-size: 13px;
    }}
    .footer a {{ color: var(--accent); text-decoration: none; }}
  </style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <div class="header-title">
        <h1>⚡ LLM Speed & Latency Benchmark</h1>
        <p>Real-time streaming evaluation report for OpenAI-compatible endpoint</p>
        <div style="margin-top: 10px;">
          <span class="endpoint-badge">🔗 <span id="ep-display"></span></span>
          <span style="font-size: 13px; color: var(--text-muted); margin-left: 12px;" id="timestamp-display"></span>
        </div>
      </div>
      <div class="actions">
        <button class="btn" onclick="copyMarkdown()">📋 Copy Markdown</button>
        <button class="btn" onclick="downloadJSON()">💾 Export JSON</button>
      </div>
    </div>

    <!-- Note Banner -->
    <div class="note-banner">
      <span>ℹ️</span> <span><strong>Note:</strong> Non-available fund models are skipped.</span>
    </div>

    <!-- KPIs -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Tested Models</div>
        <div class="kpi-value" id="kpi-total">0</div>
        <div class="kpi-sub" id="kpi-pass-rate">0% passed</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Fastest TTFT</div>
        <div class="kpi-value" style="color: var(--accent);" id="kpi-ttft">—</div>
        <div class="kpi-sub" id="kpi-ttft-model">—</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Peak Speed</div>
        <div class="kpi-value" style="color: var(--green);" id="kpi-speed">—</div>
        <div class="kpi-sub" id="kpi-speed-model">—</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Active Success Rate</div>
        <div class="kpi-value" style="color: var(--green);" id="kpi-success">0/0</div>
        <div class="kpi-sub" id="kpi-failed-count">0 skipped/failed</div>
      </div>
    </div>

    <!-- Controls -->
    <div class="controls">
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" id="searchInput" placeholder="Filter by model name..." oninput="renderTable()" />
      </div>
      <div class="filter-pills">
        <button class="pill active" onclick="setFilter('ALL', this)">All</button>
        <button class="pill" onclick="setFilter('PASS', this)">🟢 Passed</button>
        <button class="pill" onclick="setFilter('SKIPPED', this)">⚪ Skipped</button>
        <button class="pill" onclick="setFilter('FAIL', this)">🔴 Failed</button>
      </div>
    </div>

    <!-- Table -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width: 40px;">#</th>
            <th onclick="sortTable('model')">Model ID</th>
            <th onclick="sortTable('status')">Status</th>
            <th onclick="sortTable('avg_ttft')">TTFT</th>
            <th onclick="sortTable('avg_total')">Total Time</th>
            <th onclick="sortTable('avg_tps')">Generation Speed</th>
            <th>Output Preview / Notes</th>
          </tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>

    <div class="footer">
      Generated by <a href="https://github.com/mijanlab/LLMtest" target="_blank">llmtest</a> • Zero-dependency LLM evaluation toolkit
    </div>
  </div>

  <!-- Detail Modal -->
  <div class="modal-backdrop" id="modalBackdrop" onclick="closeModal(event)">
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div class="modal-title" id="modalTitle">Model Details</div>
        <button class="modal-close" onclick="closeModalDirect()">&times;</button>
      </div>
      <div id="modalBody"></div>
    </div>
  </div>

  <script>
    const DATA = {raw_data_json};
    let currentStatusFilter = 'ALL';
    let sortColumn = 'avg_ttft';
    let sortDirection = 'asc';

    document.getElementById('ep-display').textContent = DATA.endpoint;
    document.getElementById('timestamp-display').textContent = DATA.tested_at;

    // Calculate KPIs
    const results = DATA.results || [];
    const passed = results.filter(r => r.status === 'PASS');
    const skipped = results.filter(r => r.status === 'SKIPPED');
    const failed = results.filter(r => r.status === 'FAIL');
    const total = results.length;
    const passCount = passed.length;
    const skipCount = skipped.length;
    const activeTotal = total - skipCount;
    const passPct = activeTotal ? Math.round((passCount / activeTotal) * 100) : 0;

    document.getElementById('kpi-total').textContent = total;
    document.getElementById('kpi-pass-rate').textContent = `${{passCount}} passed, ${{skipCount}} skipped`;
    document.getElementById('kpi-success').textContent = `${{passCount}}/${{activeTotal}}`;
    document.getElementById('kpi-failed-count').textContent = `${{skipCount}} skipped (no funds), ${{failed.length}} failed`;

    const ttftList = passed.filter(r => r.avg_ttft !== null);
    if (ttftList.length) {{
      ttftList.sort((a, b) => a.avg_ttft - b.avg_ttft);
      const best = ttftList[0];
      const val = best.avg_ttft < 1 ? `${{Math.round(best.avg_ttft * 1000)}} ms` : `${{best.avg_ttft.toFixed(2)}} s`;
      document.getElementById('kpi-ttft').textContent = val;
      document.getElementById('kpi-ttft-model').textContent = best.model;
    }}

    const tpsList = passed.filter(r => r.avg_tps !== null);
    if (tpsList.length) {{
      tpsList.sort((a, b) => b.avg_tps - a.avg_tps);
      const best = tpsList[0];
      document.getElementById('kpi-speed').textContent = `${{best.avg_tps.toFixed(1)}} tok/s`;
      document.getElementById('kpi-speed-model').textContent = best.model;
    }}

    const maxTTFT = Math.max(...results.map(r => r.avg_ttft || 0), 1);
    const maxTPS = Math.max(...results.map(r => r.avg_tps || 0), 1);

    function setFilter(status, el) {{
      currentStatusFilter = status;
      document.querySelectorAll('.filter-pills .pill').forEach(p => p.classList.remove('active'));
      el.classList.add('active');
      renderTable();
    }}

    function sortTable(col) {{
      if (sortColumn === col) {{
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
      }} else {{
        sortColumn = col;
        sortDirection = 'asc';
      }}
      renderTable();
    }}

    function renderTable() {{
      const query = (document.getElementById('searchInput').value || '').toLowerCase();
      let filtered = results.filter(r => {{
        if (currentStatusFilter !== 'ALL' && r.status !== currentStatusFilter) return false;
        if (query && !r.model.toLowerCase().includes(query)) return false;
        return true;
      }});

      filtered.sort((a, b) => {{
        let valA = a[sortColumn];
        let valB = b[sortColumn];
        if (valA === null || valA === undefined) valA = 999999;
        if (valB === null || valB === undefined) valB = 999999;
        if (typeof valA === 'string') {{
          return sortDirection === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }}
        return sortDirection === 'asc' ? valA - valB : valB - valA;
      }});

      const tbody = document.getElementById('tableBody');
      tbody.innerHTML = '';

      filtered.forEach((r, idx) => {{
        const tr = document.createElement('tr');
        tr.className = 'clickable';
        tr.onclick = () => openModal(r);

        let badgeClass = 'badge-fail';
        let badgeText = `🔴 FAIL`;
        if (r.status === 'PASS') {{
          badgeClass = 'badge-pass';
          badgeText = `🟢 PASS`;
        }} else if (r.status === 'PARTIAL') {{
          badgeClass = 'badge-par';
          badgeText = `🟡 PAR`;
        }} else if (r.status === 'SKIPPED') {{
          badgeClass = 'badge-skip';
          badgeText = `⚪ SKIP`;
        }}

        const ttftStr = r.avg_ttft !== null ? (r.avg_ttft < 1 ? `${{Math.round(r.avg_ttft * 1000)}} ms` : `${{r.avg_ttft.toFixed(3)}} s`) : '—';
        const totalStr = r.avg_total !== null ? `${{r.avg_total.toFixed(3)}} s` : '—';
        const tpsStr = r.avg_tps !== null ? `${{r.avg_tps.toFixed(1)}} tok/s` : '—';

        const ttftPct = r.avg_ttft ? Math.min(100, Math.round((r.avg_ttft / maxTTFT) * 100)) : 0;
        const tpsPct = r.avg_tps ? Math.min(100, Math.round((r.avg_tps / maxTPS) * 100)) : 0;

        let note = '—';
        if (r.status === 'PASS') {{
          note = `"${{r.sample_preview || ''}}"`;
        }} else if (r.status === 'SKIPPED') {{
          note = 'Non-available fund (skipped)';
        }} else {{
          note = (r.errors && r.errors.length) ? r.errors.join('; ') : 'Execution error';
        }}

        tr.innerHTML = `
          <td style="color: var(--text-muted); font-size: 13px;">${{idx + 1}}</td>
          <td><span class="model-name">${{r.model}}</span></td>
          <td><span class="badge ${{badgeClass}}">${{badgeText}}</span></td>
          <td>
            <div class="latency-bar-wrap">
              <span>${{ttftStr}}</span>
              <div class="bar"><div class="bar-fill-ttft" style="width: ${{ttftPct}}%;"></div></div>
            </div>
          </td>
          <td><span style="font-family: var(--mono); font-size: 13px;">${{totalStr}}</span></td>
          <td>
            <div class="latency-bar-wrap">
              <span>${{tpsStr}}</span>
              <div class="bar"><div class="bar-fill-speed" style="width: ${{tpsPct}}%;"></div></div>
            </div>
          </td>
          <td><div class="preview-text" title="${{note.replace(/"/g, '&quot;')}}">${{note}}</div></td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    function openModal(r) {{
      document.getElementById('modalTitle').textContent = r.model;
      const ttftStr = r.avg_ttft !== null ? (r.avg_ttft < 1 ? `${{Math.round(r.avg_ttft * 1000)}} ms` : `${{r.avg_ttft.toFixed(3)}} s`) : '—';
      const totalStr = r.avg_total !== null ? `${{r.avg_total.toFixed(3)}} s` : '—';
      const tpsStr = r.avg_tps !== null ? `${{r.avg_tps.toFixed(1)}} tok/s` : '—';
      let previewText = r.sample_preview || (r.errors && r.errors.length ? r.errors.join('\\n') : 'No output recorded');
      if (r.status === 'SKIPPED') {{
        previewText = 'Model skipped from active evaluation: Non-available fund / insufficient credits.';
      }}

      document.getElementById('modalBody').innerHTML = `
        <div class="detail-row"><span class="detail-label">Status</span><span class="detail-val">${{r.status}} (${{r.success}}/${{r.runs}} successful)</span></div>
        <div class="detail-row"><span class="detail-label">Time to First Token (TTFT)</span><span class="detail-val">${{ttftStr}}</span></div>
        <div class="detail-row"><span class="detail-label">Total Duration</span><span class="detail-val">${{totalStr}}</span></div>
        <div class="detail-row"><span class="detail-label">Streaming Speed</span><span class="detail-val">${{tpsStr}}</span></div>
        <div style="margin-top: 16px;">
          <span class="detail-label">Output Preview / Notes</span>
          <div class="preview-box">${{previewText}}</div>
        </div>
      `;
      document.getElementById('modalBackdrop').classList.add('open');
    }}

    function closeModalDirect() {{
      document.getElementById('modalBackdrop').classList.remove('open');
    }}

    function closeModal(e) {{
      if (e.target.id === 'modalBackdrop') {{
        closeModalDirect();
      }}
    }}

    function copyMarkdown() {{
      let md = "| # | Model ID | Status | TTFT | Total Time | Speed | Output Preview |\\n|---|---|---|---|---|---|---|\\n";
      results.forEach((r, idx) => {{
        const ttftStr = r.avg_ttft ? (r.avg_ttft < 1 ? `${{Math.round(r.avg_ttft * 1000)}} ms` : `${{r.avg_ttft.toFixed(3)}} s`) : '—';
        const totalStr = r.avg_total ? `${{r.avg_total.toFixed(3)}} s` : '—';
        const tpsStr = r.avg_tps ? `${{r.avg_tps.toFixed(1)}} tok/s` : '—';
        const preview = (r.sample_preview || (r.errors || []).join(' ')).replace(/\\|/g, '\\\\|').replace(/\\n/g, ' ');
        md += `| ${{idx + 1}} | \`${{r.model}}\` | ${{r.status}} | ${{ttftStr}} | ${{totalStr}} | ${{tpsStr}} | ${{preview.slice(0, 50)}} |\\n`;
      }});
      navigator.clipboard.writeText(md).then(() => alert('Markdown table copied to clipboard!'));
    }}

    function downloadJSON() {{
      const blob = new Blob([JSON.stringify(DATA, null, 2)], {{ type: 'application/json' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'benchmark_report.json';
      a.click();
    }}

    renderTable();
  </script>
</body>
</html>
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    abs_path = os.path.abspath(filepath)
    file_uri = f"file:///{abs_path.replace(os.sep, '/')}"
    print(f" {CLR_GREEN}✔{CLR_RESET} Interactive Web UI report : {CLR_CYAN}{file_uri}{CLR_RESET} {CLR_GRAY}(Ctrl+Click to view){CLR_RESET}")

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
                err_text = (res.stderr.strip() or res.stdout.strip())
                if err_text:
                    error_msgs.append(err_text)
        except Exception as e:
            error_msgs.append(str(e))

    # 3. Try global pip3 / pip as fallback if still not succeeded
    if not success:
        for pip_cmd_name in ["pip3", "pip"]:
            pip_bin = shutil.which(pip_cmd_name)
            if pip_bin:
                cmd = [pip_bin, "install", "--upgrade", "--no-cache-dir", repo_url]
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True)
                    if res.returncode == 0:
                        success = True
                        break
                    else:
                        err_text = (res.stderr.strip() or res.stdout.strip())
                        if err_text:
                            error_msgs.append(err_text)
                except Exception as e:
                    error_msgs.append(str(e))

    # 4. Try pipx as general fallback if available
    if not success and shutil.which("pipx"):
        cmd = ["pipx", "install", "--force", repo_url]
        try:
            res = subprocess.run(cmd)
            if res.returncode == 0:
                success = True
        except Exception as e:
            error_msgs.append(str(e))

    if success:
        print(f"\n {CLR_GREEN}✔{CLR_RESET} {CLR_BOLD}llmtest successfully updated!{CLR_RESET}\n")
    else:
        print(f"\n {CLR_RED}✖ Update failed.{CLR_RESET}")
        if error_msgs:
            print(f" {CLR_GRAY}Details:{CLR_RESET} {error_msgs[-1]}")
        print(f"\n {CLR_GRAY}Try updating manually:{CLR_RESET}")
        print(f"   {CLR_CYAN}pipx install --force {repo_url}{CLR_RESET}   (for pipx)")
        print(f"   {CLR_CYAN}pip3 install --upgrade {repo_url}{CLR_RESET}  (for pip3)\n")
    sys.exit(0)

def handle_uninstall():
    """Uninstalls llmtest from the current environment (pipx / pip / pip3)."""
    print(f"\n{CLR_YELLOW}⚠ You are about to uninstall llmtest.{CLR_RESET}")
    try:
        confirm = input(" Are you sure you want to proceed? (y/N): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{CLR_GRAY}Cancelled.{CLR_RESET}\n")
        sys.exit(0)

    if confirm not in ["y", "yes"]:
        print(f"\n{CLR_GRAY}Uninstallation cancelled.{CLR_RESET}\n")
        sys.exit(0)

    success = False

    # 1. If running under pipx
    if is_pipx_environment() and shutil.which("pipx"):
        cmd = ["pipx", "uninstall", "llmtest"]
        try:
            res = subprocess.run(cmd)
            if res.returncode == 0:
                success = True
        except Exception:
            pass

    # 2. Try sys.executable -m pip
    if not success:
        cmd = [sys.executable, "-m", "pip", "uninstall", "-y", "llmtest"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                success = True
        except Exception:
            pass

    # 3. Try global pip3 / pip
    if not success:
        for pip_cmd_name in ["pip3", "pip"]:
            pip_bin = shutil.which(pip_cmd_name)
            if pip_bin:
                cmd = [pip_bin, "uninstall", "-y", "llmtest"]
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True)
                    if res.returncode == 0:
                        success = True
                        break
                except Exception:
                    pass

    # 4. Try pipx general fallback
    if not success and shutil.which("pipx"):
        cmd = ["pipx", "uninstall", "llmtest"]
        try:
            res = subprocess.run(cmd)
            if res.returncode == 0:
                success = True
        except Exception:
            pass

    if success:
        print(f"\n {CLR_GREEN}✔{CLR_RESET} {CLR_BOLD}llmtest has been successfully uninstalled.{CLR_RESET}\n")
    else:
        print(f"\n {CLR_RED}✖ Uninstall failed.{CLR_RESET}")
        print(f" {CLR_GRAY}Try running manually:{CLR_RESET}")
        print(f"   {CLR_CYAN}pipx uninstall llmtest{CLR_RESET} (if installed via pipx)")
        print(f"   {CLR_CYAN}pip3 uninstall llmtest{CLR_RESET} (if installed via pip3)\n")
    sys.exit(0)

def prompt_wizard():
    print(BANNER + "\n")
    env_endpoint = os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_ENDPOINT") or "https://api.openai.com/v1"
    env_key = os.environ.get("OPENAI_API_KEY") or ""

    ep_prompt = f" {CLR_BOLD}◆ API Endpoint URL{CLR_RESET} {CLR_GRAY}[{env_endpoint}]{CLR_RESET}: "
    try:
        raw_ep = input(ep_prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{CLR_GRAY}Cancelled.{CLR_RESET}")
        sys.exit(0)
    endpoint = raw_ep or env_endpoint

    key_hint = f"{CLR_GRAY}(masked, press Enter if none or skip){CLR_RESET}"
    if env_key:
        key_hint = f"{CLR_GRAY}(found in $OPENAI_API_KEY, press Enter to use){CLR_RESET}"
    key_prompt = f" {CLR_BOLD}◆ API Key{CLR_RESET} {key_hint}: "
    try:
        raw_key = input(key_prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{CLR_GRAY}Cancelled.{CLR_RESET}")
        sys.exit(0)
    key = raw_key if raw_key else (env_key if not raw_key else "")

    filter_prompt = f" {CLR_BOLD}◆ Filter Models{CLR_RESET} {CLR_GRAY}(optional, e.g. 'flash', 'free', 'gpt' or Enter for all){CLR_RESET}: "
    try:
        model_filter = input(filter_prompt).strip()
    except (KeyboardInterrupt, EOFError):
        model_filter = ""

    conc_prompt = f" {CLR_BOLD}◆ Concurrency{CLR_RESET} {CLR_GRAY}[default: 3]{CLR_RESET}: "
    try:
        raw_conc = input(conc_prompt).strip()
        concurrency = int(raw_conc) if raw_conc.isdigit() and int(raw_conc) > 0 else 3
    except (KeyboardInterrupt, EOFError):
        concurrency = 3

    print()
    return endpoint, key, model_filter, concurrency

def main():
    # Early intercept for update / uninstall subcommands or flags
    if len(sys.argv) > 1:
        first_arg = sys.argv[1].strip().lower()
        if first_arg in ["update", "upgrade", "--update", "--upgrade"]:
            handle_update()
        elif first_arg in ["uninstall", "remove", "--uninstall", "--remove"]:
            handle_uninstall()

    parser = argparse.ArgumentParser(
        prog="llmtest",
        description="⚡ Fast CLI tool to discover & benchmark all LLM models for any OpenAI-compatible endpoint.",
        usage="%(prog)s [endpoint | update | uninstall] [key] [filter] [options]"
    )
    parser.add_argument("pos_endpoint", nargs="?", default="", help="API endpoint URL, or 'update' / 'uninstall' (e.g. https://lab.proclfy.link/v1)")
    parser.add_argument("pos_key", nargs="?", default="", help="API Key (optional)")
    parser.add_argument("pos_filter", nargs="?", default="", help="Model filter keyword (e.g. 'free', 'flash')")

    # Management flags
    parser.add_argument("--update", action="store_true", help="Update llmtest to the latest version from GitHub")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall llmtest from your Python environment")

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
    parser.add_argument("--output-json", type=str, default="benchmark_report.json", help="JSON report output path")
    parser.add_argument("--open", action="store_true", help="Automatically open interactive Web UI report in browser")

    args = parser.parse_args()

    if args.update:
        handle_update()
    if args.uninstall:
        handle_uninstall()

    endpoint = args.pos_endpoint or args.endpoint
    key = args.pos_key or args.key
    model_filter = args.pos_filter or args.filter
    concurrency = args.concurrency

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
                if r["status"] == "PASS":
                    status_badge = f"{CLR_GREEN}🟢 PASS{CLR_RESET}"
                elif r["status"] == "PARTIAL":
                    status_badge = f"{CLR_YELLOW}🟡 PAR {CLR_RESET}"
                elif r["status"] == "SKIPPED":
                    status_badge = f"{CLR_GRAY}⚪ SKIP{CLR_RESET}"
                else:
                    status_badge = f"{CLR_RED}🔴 FAIL{CLR_RESET}"

                ttft_dsp = f"{r['avg_ttft']*1000:.0f}ms" if r['avg_ttft'] and r['avg_ttft'] < 1 else (f"{r['avg_ttft']:.2f}s" if r['avg_ttft'] else "—")
                tps_dsp = f"{r['avg_tps']:.1f} tok/s" if r['avg_tps'] else "—"
                model_dsp = (r['model'][:26] + "...") if len(r['model']) > 29 else r['model']
                print(f" [{len(results):>2}/{total_models}] {status_badge}  {model_dsp:<29} │ TTFT: {ttft_dsp:<7} │ Speed: {tps_dsp:<10}")
            except Exception as exc:
                print(f" {CLR_RED}✖ Error testing {m_info['id']}: {exc}{CLR_RESET}")

    total_wall_time = time.perf_counter() - start_bench

    # Sort results: PASS first, then PARTIAL, then SKIPPED, then FAIL, ordered by TTFT
    results.sort(key=lambda x: (
        0 if x["status"] == "PASS" else (1 if x["status"] == "PARTIAL" else (2 if x["status"] == "SKIPPED" else 3)),
        x["avg_ttft"] or 999
    ))

    # Display clean table
    print_table(results)

    # Display executive summary card
    print_summary_card(results, total_wall_time)

    # Export reports
    print(f"{CLR_BOLD}📁 Exported Reports:{CLR_RESET}")
    if args.output_html:
        export_html_report(results, args.output_html, endpoint)
    if args.output_md:
        export_markdown_report(results, args.output_md, endpoint)
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump({"endpoint": endpoint, "tested_at": time.time(), "results": results}, f, indent=2)
        print(f" {CLR_GREEN}✔{CLR_RESET} JSON report     : {CLR_CYAN}{os.path.abspath(args.output_json)}{CLR_RESET}")

    # Auto-open in browser if requested
    if args.open and args.output_html:
        html_uri = f"file:///{os.path.abspath(args.output_html).replace(os.sep, '/')}"
        webbrowser.open(html_uri)

    print(f"\n {CLR_GRAY}💡 Tip: You can run directly in 1 line next time:{CLR_RESET}")
    clean_key = "<your_api_key>" if key else ""
    filt_arg = f" {model_filter}" if model_filter else ""
    print(f"    {CLR_CYAN}python test_all_models.py {endpoint} {clean_key}{filt_arg}{CLR_RESET}\n")

if __name__ == "__main__":
    main()



