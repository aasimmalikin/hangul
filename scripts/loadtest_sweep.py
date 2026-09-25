#!/usr/bin/env python3
"""Concurrency-sweep load test for hangul-harness. Run ON the EC2 instance
(hits localhost:8000).

Fires requests at increasing concurrency levels and measures, at each level:
  - latency (p50/p95/p99)
  - throughput (requests/second)
  - error rate (%)
  - cost, total tokens, steps (avg)

Compares each load level against the concurrency=1 baseline, so you see how
the system degrades under stress and where it saturates. All questions distinct
=> cache misses. Excludes approval-triggering filesystem writes.

Uses threads for concurrency (each request is a blocking HTTP call; threads let
them overlap). Pure standard library.

Usage (ON the EC2 instance):
    python3 loadtest_sweep.py
"""
import time
import statistics
import urllib.request
import json
import threading
import queue

API_URL = "http://localhost:8000"

# Concurrency levels to test. 1 = baseline, then increasing stress.
CONCURRENCY_LEVELS = [1, 2, 4, 8]
# Requests fired at EACH level.
REQUESTS_PER_LEVEL = 20

QUESTIONS = [
    "What is the current USD to INR exchange rate?",
    "What is the current price of gold per ounce?",
    "Who is the current president of France?",
    "What is the latest version of Python?",
    "What is the current population of Japan?",
    "What is the current price of Bitcoin in USD?",
    "Search the web for the current USD to INR rate, then calculate what 45000 USD is in INR.",
    "Find the current price of gold per ounce, then calculate the cost of 12 ounces.",
    "Look up the current Bitcoin price, then calculate the value of 3.5 Bitcoin.",
    "Find the current USD to EUR rate and calculate what 8200 USD converts to.",
    "Search for the current population of India and the United States, then calculate how many times larger India is.",
    "Find the current prices of gold and silver per ounce, then calculate the total for 5 ounces of each.",
    "Look up the latest prices of Bitcoin and Ethereum, then calculate the cost of 2 Bitcoin and 10 Ethereum.",
    "Find the current populations of Canada and Australia, then compute the difference.",
    "Calculate 15% of 84000.",
    "What is 2340 multiplied by 18?",
    "Calculate the compound total of 50000 at 8 percent for 3 years.",
    "What is 96500 divided by 23?",
]

_qcounter = 0
_qlock = threading.Lock()


def next_question():
    global _qcounter
    with _qlock:
        i = _qcounter
        _qcounter += 1
    base = QUESTIONS[i % len(QUESTIONS)]
    return f"{base} (q{i})"  # unique => cache miss


def percentile(vals, p):
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * (p / 100)
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    frac = k - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def one_request():
    q = next_question()
    data = json.dumps({"question": q}).encode()
    req = urllib.request.Request(
        f"{API_URL}/ask",
        data=data,
        headers={"Content-Type": "application/json",
                 "X-Session-ID": f"load-{time.time_ns()}"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read())
        elapsed = time.perf_counter() - t0
        cost = float(body.get("cost_usd") or 0)
        steps = int(body.get("steps") or 0)
        bu = body.get("budget_used") or {}
        tokens = int(bu.get("tokens") or 0)
        return {"ok": True, "latency": elapsed, "cost": cost,
                "steps": steps, "tokens": tokens}
    except Exception as e:
        return {"ok": False, "latency": time.perf_counter() - t0,
                "error": type(e).__name__}


def run_level(concurrency, n_requests):
    """Fire n_requests using `concurrency` worker threads. Measure wall time
    for throughput."""
    work = queue.Queue()
    for _ in range(n_requests):
        work.put(1)
    results = []
    rlock = threading.Lock()

    def worker():
        while True:
            try:
                work.get_nowait()
            except queue.Empty:
                return
            r = one_request()
            with rlock:
                results.append(r)
            work.task_done()

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    wall_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - wall_start

    ok = [r for r in results if r["ok"]]
    errors = len(results) - len(ok)
    lats = [r["latency"] for r in ok]
    throughput = len(ok) / wall if wall > 0 else 0

    return {
        "concurrency": concurrency,
        "total": len(results),
        "ok": len(ok),
        "errors": errors,
        "error_rate": 100 * errors / len(results) if results else 0,
        "wall": wall,
        "throughput": throughput,
        "p50": percentile(lats, 50),
        "p95": percentile(lats, 95),
        "p99": percentile(lats, 99),
        "mean_lat": statistics.mean(lats) if lats else 0,
        "avg_cost": statistics.mean([r["cost"] for r in ok]) if ok else 0,
        "avg_tokens": statistics.mean([r["tokens"] for r in ok]) if ok else 0,
        "avg_steps": statistics.mean([r["steps"] for r in ok]) if ok else 0,
    }


def main():
    print(f"Concurrency sweep against {API_URL}")
    print(f"Levels: {CONCURRENCY_LEVELS}, {REQUESTS_PER_LEVEL} requests each\n")

    rows = []
    for c in CONCURRENCY_LEVELS:
        print(f"--- Running concurrency={c} ({REQUESTS_PER_LEVEL} requests) ---")
        r = run_level(c, REQUESTS_PER_LEVEL)
        rows.append(r)
        print(f"    done in {r['wall']:.1f}s  "
              f"throughput={r['throughput']:.2f} req/s  "
              f"p95={r['p95']:.1f}s  errors={r['errors']}\n")
        time.sleep(2)  # brief cooldown between levels

    # comparison table
    print("=" * 78)
    print("CONCURRENCY SWEEP RESULTS  (baseline = concurrency 1)")
    print("=" * 78)
    hdr = (f"{'conc':>4} | {'thru(req/s)':>11} | {'p50':>6} | {'p95':>6} | "
           f"{'p99':>6} | {'err%':>5} | {'avg$':>8} | {'avgTok':>7} | {'stp':>4}")
    print(hdr)
    print("-" * 78)
    base = rows[0]
    for r in rows:
        print(f"{r['concurrency']:>4} | {r['throughput']:>11.2f} | "
              f"{r['p50']:>6.1f} | {r['p95']:>6.1f} | {r['p99']:>6.1f} | "
              f"{r['error_rate']:>5.1f} | ${r['avg_cost']:>7.5f} | "
              f"{r['avg_tokens']:>7.0f} | {r['avg_steps']:>4.1f}")

    print("\n" + "=" * 78)
    print("DEGRADATION vs BASELINE (concurrency 1)")
    print("=" * 78)
    for r in rows[1:]:
        lat_mult = r['p95'] / base['p95'] if base['p95'] else 0
        thru_mult = r['throughput'] / base['throughput'] if base['throughput'] else 0
        print(f"  concurrency {r['concurrency']}: "
              f"p95 latency {lat_mult:.1f}x baseline, "
              f"throughput {thru_mult:.1f}x baseline, "
              f"errors {r['error_rate']:.0f}%")

    # find saturation (where errors appear or throughput stops rising)
    print("\n" + "=" * 78)
    print("FINDINGS")
    print("=" * 78)
    peak = max(rows, key=lambda r: r['throughput'])
    print(f"  Peak throughput: {peak['throughput']:.2f} req/s at concurrency {peak['concurrency']}")
    first_err = next((r for r in rows if r['errors'] > 0), None)
    if first_err:
        print(f"  Errors first appear at concurrency {first_err['concurrency']} "
              f"({first_err['error_rate']:.0f}%)")
    else:
        print(f"  No errors at any tested level (up to concurrency {rows[-1]['concurrency']})")
    print(f"  Baseline p95: {base['p95']:.1f}s -> at concurrency {rows[-1]['concurrency']}: "
          f"{rows[-1]['p95']:.1f}s")
    print("\n  NOTE: single t3.micro (1GB/1vCPU). Saturation reflects the instance,")
    print("  not the software ceiling. Horizontal scaling would raise throughput.")


if __name__ == "__main__":
    main()