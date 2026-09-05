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
    export_csv_report,
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
            ep_input = input(f"{CLR_BOLD}1. API Endpoint URL{CLR_RESET} (e.g. https://api.openai.com/v1): ").strip()
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
    parser.add_argument("--version", "-v", action="version", version="llmtest 1.0.6", help="Show version number and exit")

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

    if args.update or (args.pos_endpoint and args.pos_endpoint.lower() in ("update", "upgrade", "--update")):
        handle_update()
    if args.uninstall or (args.pos_endpoint and args.pos_endpoint.lower() in ("uninstall", "remove", "--uninstall")):
        handle_uninstall()

    # Check if rendering existing report from JSON
    if args.report:
        handle_render_from_json(args.report, args)
        return
    if args.pos_endpoint and args.pos_endpoint.lower() in ("report", "render") and args.pos_key:
        handle_render_from_json(args.pos_key, args)
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
