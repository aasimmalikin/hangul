#!/usr/bin/env python3
"""Measure server-side latency percentiles for hangul-harness.

Run ON the EC2 instance (hits localhost:8000). Uses a pool of DISTINCT
questions so every request is a cache miss (cache key is question text),
each exercising the full agent path. Questions are similar in workload
(all single web-search lookups) so the percentiles describe a consistent
request type.

Usage (on the instance):
    python3 measure_latency.py
"""
import time
import statistics
import urllib.request
import json

API_URL = "http://localhost:8000"

# Distinct questions, similar workload (each one web-search lookup).
# All different text => all cache misses.
QUESTIONS = [
    "What is the current USD to INR exchange rate?",
    "What is the current price of gold per ounce?",
    "What is the current price of Bitcoin in USD?",
    "What is the current population of Japan?",
    "Who is the current president of France?",
    "What is the current price of Ethereum in USD?",
    "What is the latest version of the Python programming language?",
    "What is the current price of silver per ounce?",
    "What is the current population of Canada?",
    "What is the current USD to EUR exchange rate?",
    "What is the current price of crude oil per barrel?",
    "Who is the current CEO of Microsoft?",
    "What is the current population of Australia?",
    "What is the current USD to GBP exchange rate?",
    "What is the latest iPhone model released?",
    "What is the current price of natural gas?",
    "What is the current population of Germany?",
    "Who is the current prime minister of Canada?",
    "What is the current USD to JPY exchange rate?",
    "What is the current price of platinum per ounce?",
    "What is the current population of Brazil?",
    "What is the current price of copper per pound?",
    "What is the latest Android version released?",
    "What is the current USD to AUD exchange rate?",
    "What is the current population of Mexico?",
]

N_REQUESTS = 50


def make_question(i):
    base = QUESTIONS[i % len(QUESTIONS)]
    round_num = i // len(QUESTIONS)
    if round_num == 0:
        return base
    return f"{base} (as of today, query {i})"


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
                 "X-Session-ID": f"latency-{i}"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read()
        return time.perf_counter() - t0, body


def main():
    latencies = []
    cached_hits = 0
    errors = 0
    print(f"Firing {N_REQUESTS} requests at {API_URL}/ask (unique questions)\n")

    for i in range(N_REQUESTS):
        q = make_question(i)
        try:
            elapsed, body = one_request(i, q)
            try:
                parsed = json.loads(body)
                if parsed.get("cached") is True:
                    cached_hits += 1
            except Exception:
                pass
            latencies.append(elapsed)
            print(f"  [{i+1:3}/{N_REQUESTS}] {elapsed:6.2f}s  {q[:45]}")
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
        print(f"\nWARNING: {cached_hits} cache hits detected - skewing low.")
    print(f'\nResume line: "p95 {percentile(latencies,95):.1f}s, p99 '
          f'{percentile(latencies,99):.1f}s across {len(latencies)} live '
          f'web-search QA requests (p50 {percentile(latencies,50):.1f}s)."')


if __name__ == "__main__":
    main()