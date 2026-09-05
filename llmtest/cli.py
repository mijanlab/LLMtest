#!/usr/bin/env python3
"""
llmtest CLI Entrypoint
----------------------
Invoked globally via `llmtest` or `llm-test` command.
Modern, user-friendly interactive & one-line benchmark CLI.
"""

import os
import sys
import time
import json
import shutil
import argparse
import subprocess
import webbrowser
import concurrent.futures
from llmtest.benchmark import (
    normalize_urls,
    fetch_available_models,
    benchmark_model,
    print_table,
    print_summary_card,
    export_markdown_report,
    export_html_report,
    CLR_RESET,
    CLR_BOLD,
    CLR_DIM,
    CLR_CYAN,
    CLR_GREEN,
    CLR_YELLOW,
    CLR_RED,
    CLR_GRAY
)

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
    """Runs a streamlined, friendly interactive wizard for first-time or no-arg runs."""
    print(BANNER + "\n")

    # Smart defaults from environment if present
    env_endpoint = os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_ENDPOINT") or "https://api.openai.com/v1"
    env_key = os.environ.get("OPENAI_API_KEY") or ""

    # 1. Endpoint
    ep_prompt = f" {CLR_BOLD}◆ API Endpoint URL{CLR_RESET} {CLR_GRAY}[{env_endpoint}]{CLR_RESET}: "
    try:
        raw_ep = input(ep_prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{CLR_GRAY}Cancelled.{CLR_RESET}")
        sys.exit(0)
    endpoint = raw_ep or env_endpoint

    # 2. API Key
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

    # 3. Model Filter
    filter_prompt = f" {CLR_BOLD}◆ Filter Models{CLR_RESET} {CLR_GRAY}(optional, e.g. 'flash', 'free', 'gpt' or Enter for all){CLR_RESET}: "
    try:
        model_filter = input(filter_prompt).strip()
    except (KeyboardInterrupt, EOFError):
        model_filter = ""

    # 4. Concurrency
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
    # Positional shortcuts (for ultra-short command lines)
    parser.add_argument("pos_endpoint", nargs="?", default="", help="API endpoint URL, or 'update' / 'uninstall' (e.g. https://lab.proclfy.link/v1)")
    parser.add_argument("pos_key", nargs="?", default="", help="API Key (optional)")
    parser.add_argument("pos_filter", nargs="?", default="", help="Model filter keyword (e.g. 'free', 'flash')")

    # Version flag
    parser.add_argument("--version", "-v", action="version", version="llmtest 1.0.1", help="Show version number and exit")

    # Management flags
    parser.add_argument("--update", action="store_true", help="Update llmtest to the latest version from GitHub")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall llmtest from your Python environment")

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
    print(f"{CLR_BOLD}📁 Exported Reports:{CLR_RESET}")
    if args.output_html:
        export_html_report(results, args.output_html, endpoint)
    if args.output_md:
        export_markdown_report(results, args.output_md, endpoint)
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump({"endpoint": endpoint, "tested_at": time.time(), "results": results}, f, indent=2)
        print(f" {CLR_GREEN}✔{CLR_RESET} JSON report     : {CLR_CYAN}{os.path.abspath(args.output_json)}{CLR_RESET}")

    # Auto-open in browser if requested or interactive
    if args.open and args.output_html:
        html_uri = f"file:///{os.path.abspath(args.output_html).replace(os.sep, '/')}"
        webbrowser.open(html_uri)

    # Helpful tip for one-liner syntax
    print(f"\n {CLR_GRAY}💡 Tip: You can run directly in 1 line next time:{CLR_RESET}")
    clean_key = "<your_api_key>" if key else ""
    filt_arg = f" {model_filter}" if model_filter else ""
    print(f"    {CLR_CYAN}llmtest {endpoint} {clean_key}{filt_arg}{CLR_RESET}\n")

if __name__ == "__main__":
    main()



