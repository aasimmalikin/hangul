"""Locust load test for hangul-harness — captures latency, tokens, cost, and steps.

Run from your laptop via SSH tunnel, or on the instance. Each user sends
distinct questions (cache misses) across a mixed tool workload. Locust reports
latency percentiles + throughput + failure rate natively; a request-event hook
records per-request total tokens, cost (USD), and steps, printed as a summary
when the run ends.

Install (laptop, in venv):  pip install locust
Tunnel (terminal 1):        ssh -i ~/agentic-qa-key.pem -L 8000:localhost:8000 ec2-user@13.233.158.219
Run (terminal 2):           locust -f locustfile.py --headless -u 4 -r 1 -t 2m --host http://localhost:8000
"""
import itertools
import threading
import statistics
from locust import HttpUser, task, between, events

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
    "Search for the current population of India and the United States, then calculate how many times larger India is.",
    "Find the current prices of gold and silver per ounce, then calculate the total for 5 ounces of each.",
    "Calculate 15% of 84000.",
    "What is 2340 multiplied by 18?",
    "Calculate the compound total of 50000 at 8 percent for 3 years.",
]

_counter = itertools.count()
_lock = threading.Lock()

# per-request metrics collected across all users (thread-safe)
_metrics_lock = threading.Lock()
_tokens = []
_costs = []
_steps = []


def next_question():
    with _lock:
        i = next(_counter)
    return f"{QUESTIONS[i % len(QUESTIONS)]} (q{i})"


def percentile(vals, p):
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * (p / 100)
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    frac = k - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


class AgentUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def ask(self):
        q = next_question()
        with self.client.post(
            "/ask",
            json={"question": q},
            headers={"X-Session-ID": f"locust-{q[-8:]}"},
            name="/ask",
            catch_response=True,
            timeout=180,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            try:
                body = resp.json()
                cost = float(body.get("cost_usd") or 0)
                steps = int(body.get("steps") or 0)
                bu = body.get("budget_used") or {}
                tokens = int(bu.get("tokens") or 0)
                with _metrics_lock:
                    _costs.append(cost)
                    _steps.append(steps)
                    _tokens.append(tokens)
                resp.success()
            except Exception as e:
                resp.failure(f"parse error: {e}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("\n" + "=" * 54)
    print("PER-REQUEST METRICS (from successful responses)")
    print("=" * 54)
    if not _tokens:
        print("  no successful responses captured.")
        return

    def block(label, vals, fmt, prefix=""):
        print(f"\n--- {label} ---")
        print(f"  p50 : {prefix}{percentile(vals,50):{fmt}}")
        print(f"  p90 : {prefix}{percentile(vals,90):{fmt}}")
        print(f"  p95 : {prefix}{percentile(vals,95):{fmt}}")
        print(f"  p99 : {prefix}{percentile(vals,99):{fmt}}")
        print(f"  max : {prefix}{max(vals):{fmt}}")
        print(f"  mean: {prefix}{statistics.mean(vals):{fmt}}")

    block("TOTAL TOKENS (per request)", _tokens, ".0f")
    block("COST (USD per request)", _costs, ".5f", prefix="$")
    block("STEPS (trajectory length)", _steps, ".1f")

    print("\n" + "=" * 54)
    print("SUMMARY")
    print("=" * 54)
    print(f"  requests captured : {len(_tokens)}")
    print(f"  avg tokens/request: {statistics.mean(_tokens):.0f}")
    print(f"  avg cost/request  : ${statistics.mean(_costs):.5f}")
    print(f"  cost per 1000 req : ${statistics.mean(_costs)*1000:.2f}")
    print(f"  avg steps/request : {statistics.mean(_steps):.1f}  (max {max(_steps)})")
    print("\n(latency percentiles + throughput + failure rate are in Locust's")
    print(" own table above; these are the LLM-specific per-request metrics.)")