#!/usr/bin/env python3
"""Measure server-side latency percentiles for hangul-harness across a MIX of
tool combinations (factual, web search, RAG, calculator, multi-tool reasoning).

Run ON the EC2 instance (hits localhost:8000). Excludes approval-triggering
filesystem writes (those pause for human input and can't be measured as a
clean round-trip). All questions are distinct => cache misses.

For the RAG questions to work, upload the Nimbus doc first, OR they'll just
fall back to web/other tools (still a valid request, just different grounding).

Usage (on the instance):
    python3 measure_latency_mixed.py
"""
import time
import statistics
import urllib.request
import json

API_URL = "http://localhost:8000"
N_REQUESTS = 50

# A realistic mix across tool types. All distinct text => cache misses.
QUESTIONS = [
    # --- simple factual / single web lookup (fast) ---
    "What is the current USD to INR exchange rate?",
    "What is the current price of gold per ounce?",
    "Who is the current president of France?",
    "What is the latest version of Python?",
    "What is the current population of Japan?",
    "What is the current price of Bitcoin in USD?",
    # --- calculator + web (2 tools) ---
    "Search the web for the current USD to INR rate, then calculate what 45000 USD is in INR.",
    "Find the current price of gold per ounce, then calculate the cost of 12 ounces.",
    "Look up the current Bitcoin price, then calculate the value of 3.5 Bitcoin.",
    "Find the current USD to EUR rate and calculate what 8200 USD converts to.",
    # --- multi-step reasoning (more tools, slower) ---
    "Search for the current population of India and the United States, then calculate how many times larger India is.",
    "Find the current prices of gold and silver per ounce, then calculate the total for 5 ounces of each.",
    "Look up the latest prices of Bitcoin and Ethereum, then calculate the cost of 2 Bitcoin and 10 Ethereum.",
    "Find the current populations of Canada and Australia, then compute the difference.",
    # --- calculator only (fast, no web) ---
    "Calculate 15% of 84000.",
    "What is 2340 multiplied by 18?",
    "Calculate the compound total of 50000 at 8 percent for 3 years.",
    "What is 96500 divided by 23?",
]


def make_question(i):
    base = QUESTIONS[i % len(QUESTIONS)]
    if i // len(QUESTIONS) == 0:
        return base
    return f"{base} (query {i})"


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (p / 100)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def one_request(i, question):
    data = json.dumps({"question": question}).encode()
    req = urllib.request.Request(
        f"{API_URL}/ask",
        data=data,
        headers={"Content-Type": "application/json",
                 "X-Session-ID": f"latency-mix-{i}"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = resp.read()
        return time.perf_counter() - t0, body


def main():
    latencies = []
    cached_hits = 0
    errors = 0
    print(f"Firing {N_REQUESTS} mixed-workload requests at {API_URL}/ask\n")

    for i in range(N_REQUESTS):
        q = make_question(i)
        try:
            elapsed, body = one_request(i, q)
            try:
                if json.loads(body).get("cached") is True:
                    cached_hits += 1
            except Exception:
                pass
            latencies.append(elapsed)
            print(f"  [{i+1:3}/{N_REQUESTS}] {elapsed:6.2f}s  {q[:50]}")
        except Exception as e:
            errors += 1
            print(f"  [{i+1:3}/{N_REQUESTS}] ERROR: {type(e).__name__}")

    if not latencies:
        print("\nNo successful requests - is the app up on localhost:8000?")
        return

    latencies.sort()
    print("\n" + "=" * 44)
    print(f"Successful: {len(latencies)}/{N_REQUESTS}  errors: {errors}  "
          f"cache-hits: {cached_hits}")
    print("=" * 44)
    print(f"  min  : {latencies[0]:6.2f}s")
    print(f"  p50  : {percentile(latencies, 50):6.2f}s")
    print(f"  p90  : {percentile(latencies, 90):6.2f}s")
    print(f"  p95  : {percentile(latencies, 95):6.2f}s")
    print(f"  p99  : {percentile(latencies, 99):6.2f}s")
    print(f"  max  : {latencies[-1]:6.2f}s")
    print(f"  mean : {statistics.mean(latencies):6.2f}s")
    print("=" * 44)
    if cached_hits:
        print(f"\nWARNING: {cached_hits} cache hits - skewing low.")
    print(f'\nResume line: "p95 {percentile(latencies,95):.1f}s, p99 '
          f'{percentile(latencies,99):.1f}s across {len(latencies)} live '
          f'mixed-workload agent requests (p50 {percentile(latencies,50):.1f}s)."')


if __name__ == "__main__":
    main()