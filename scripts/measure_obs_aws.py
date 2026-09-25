#!/usr/bin/env python3
"""Observability measurement for hangul-harness, run ON the EC2 instance against
the live deployment (localhost:8000).

Measures, across a mixed tool workload, per-request:
  - latency (s)
  - cost (USD)
  - total tokens (from budget_used.tokens)
  - steps (trajectory length / tool-call count)
  - error rate

Reports p50/p90/p95/p99 for each, plus derived metrics. All questions distinct
=> cache misses. Excludes approval-triggering filesystem writes.

Usage (ON the EC2 instance):
    python3 measure_obs_aws.py
"""
import time
import statistics
import urllib.request
import json

API_URL = "http://localhost:8000"
N_REQUESTS = 50

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


def make_question(i):
    base = QUESTIONS[i % len(QUESTIONS)]
    if i // len(QUESTIONS) == 0:
        return base
    return f"{base} (query {i})"


def percentile(vals, p):
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * (p / 100)
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    frac = k - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def stats_block(label, vals, fmt, prefix=""):
    if not vals:
        print(f"\n--- {label} --- (no data)")
        return
    print(f"\n--- {label} ---")
    for name, p in [("min", None), ("p50", 50), ("p90", 90),
                    ("p95", 95), ("p99", 99), ("max", None)]:
        if name == "min":
            v = min(vals)
        elif name == "max":
            v = max(vals)
        else:
            v = percentile(vals, p)
        print(f"  {name:4}: {prefix}{v:{fmt}}")
    print(f"  mean: {prefix}{statistics.mean(vals):{fmt}}")


def one_request(i, question):
    data = json.dumps({"question": question}).encode()
    req = urllib.request.Request(
        f"{API_URL}/ask",
        data=data,
        headers={"Content-Type": "application/json",
                 "X-Session-ID": f"obs-{i}"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = resp.read()
        return time.perf_counter() - t0, json.loads(body)


def main():
    lat, cost, total_tok, steps = [], [], [], []
    errors = 0
    print(f"Firing {N_REQUESTS} mixed requests at {API_URL}/ask\n")
    print(f"{'#':>4}  {'lat':>6}  {'cost':>9}  {'tokens':>7}  {'steps':>5}  question")

    for i in range(N_REQUESTS):
        q = make_question(i)
        try:
            elapsed, r = one_request(i, q)
            lat.append(elapsed)
            c = r.get("cost_usd")
            st = r.get("steps")
            # total tokens from budget_used.tokens
            tot = None
            bu = r.get("budget_used")
            if isinstance(bu, dict) and bu.get("tokens") is not None:
                tot = int(bu["tokens"])
            if c is not None: cost.append(float(c))
            if st is not None: steps.append(int(st))
            if tot is not None: total_tok.append(int(tot))
            print(f"{i+1:>4}  {elapsed:6.2f}  ${float(c or 0):.5f}  "
                  f"{tot or 0:>7}  {st or 0:>5}  {q[:34]}")
        except Exception as e:
            errors += 1
            print(f"{i+1:>4}  ERROR: {type(e).__name__}")

    if not lat:
        print("\nNo successful requests - is the app up on localhost:8000?")
        return

    print("\n" + "=" * 52)
    print(f"Successful: {len(lat)}/{N_REQUESTS}  errors: {errors}  "
          f"error-rate: {100*errors/N_REQUESTS:.1f}%")
    print("=" * 52)

    stats_block("LATENCY (s)", lat, "6.2f")
    stats_block("COST (USD/request)", cost, ".5f", prefix="$")
    stats_block("TOTAL TOKENS (per request)", total_tok, ".0f")
    stats_block("STEPS (trajectory length)", steps, ".1f")

    print("\n" + "=" * 52)
    print("SUMMARY / DERIVED METRICS")
    print("=" * 52)
    if cost:
        print(f"  avg cost/request  : ${statistics.mean(cost):.5f}")
        print(f"  cost per 1000 req : ${statistics.mean(cost)*1000:.2f}")
        p50c, p99c = percentile(cost, 50), percentile(cost, 99)
        if p50c > 0:
            print(f"  p99/p50 cost ratio: {p99c/p50c:.1f}x  (healthy if under 50x)")
    if total_tok:
        print(f"  avg total tokens  : {statistics.mean(total_tok):.0f}")
    if steps:
        print(f"  avg steps/request : {statistics.mean(steps):.1f}  (max {max(steps)})")

    print("\n" + "=" * 52)
    print("RESUME / README LINES")
    print("=" * 52)
    print(f'  Latency: p50 {percentile(lat,50):.1f}s / p95 {percentile(lat,95):.1f}s '
          f'/ p99 {percentile(lat,99):.1f}s')
    if cost:
        print(f'  Cost:    avg ${statistics.mean(cost):.4f}/req, '
              f'p95 ${percentile(cost,95):.4f}, p99 ${percentile(cost,99):.4f}')
    if total_tok:
        print(f'  Tokens:  p50 {percentile(total_tok,50):.0f} / '
              f'p95 {percentile(total_tok,95):.0f} / p99 {percentile(total_tok,99):.0f} '
              f'total tokens per request')
    if steps:
        print(f'  Steps:   p50 {percentile(steps,50):.0f} / p95 {percentile(steps,95):.0f} '
              f'tool-call steps per request')
    print(f'  Error rate: {100*errors/N_REQUESTS:.1f}% ({errors}/{N_REQUESTS})')


if __name__ == "__main__":
    main()