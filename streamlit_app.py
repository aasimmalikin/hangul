"""hangul-harness demo frontend — clean chat up front; quality metrics and
observability live in the sidebar behind a reveal toggle."""

import uuid
import requests
import streamlit as st
#C:\Users\HP\Downloads

API_URL = "http://localhost:8000"

st.set_page_config(page_title="hangul-harness", page_icon="🧭", layout="wide")

if "session_id" not in st.session_state:
    st.session_state.session_id = "sess-" + uuid.uuid4().hex[:16]
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploaded" not in st.session_state:
    st.session_state.uploaded = []
if "pending" not in st.session_state:
    st.session_state.pending = None


def headers() -> dict:
    return {"X-Session-ID": st.session_state.session_id}


TOOL_LABELS = {
    "web_search": "🌐 web search",
    "search_docs": "📄 your documents",
    "calculator": "🧮 calculator",
}
def tool_label(name: str) -> str:
    if name.startswith("filesystem__"):
        return "📁 filesystem (MCP)"
    return TOOL_LABELS.get(name, f"🔧 {name}")


def render_badges(data: dict) -> list:
    badges = [tool_label(t) for t in data.get("tools_used", [])]
    if not data.get("tools_used"):
        badges.append("💬 direct model")
    cost = data.get("cost_usd", 0) or 0
    badges.append(f"{data.get('steps', 0)} steps · ${cost:.4f}")
    if data.get("cached"):
        badges.append("cached")
    return badges


def store_result(data: dict) -> None:
    if data.get("stopped_reason") == "pending_approval" and data.get("pending_tool"):
        st.session_state.pending = {
            "run_id": data["run_id"],
            "tool": data["pending_tool"],
            "answer": data.get("answer", ""),
        }
    else:
        st.session_state.pending = None
        st.session_state.messages.append({
            "role": "assistant",
            "content": data.get("answer", "(no answer)"),
            "badges": render_badges(data),
        })


# --- sidebar --------------------------------------------------------------
with st.sidebar:
    st.markdown("### hangul-harness")
    st.caption("an agent that picks the right tool")

    st.markdown("**Capabilities**")
    st.markdown(
        "- 🌐 Web search\n- 📄 Your documents (RAG)\n- 📁 Filesystem (MCP)\n"
        "- 🧮 Calculator\n- 💬 Direct GPT-4 chat"
    )

    st.divider()
    docs_only = st.toggle("📄 Documents only",
                          help="Answer using ONLY your uploaded documents — no web, no other tools.")

    st.divider()
    st.markdown("**Upload a document**")
    up = st.file_uploader("Upload txt, md, or pdf (max 10MB)", type=["txt", "md", "pdf"],
                          label_visibility="collapsed")
    if up is not None and up.name not in st.session_state.uploaded:
        with st.spinner(f"Indexing {up.name}…"):
            try:
                r = requests.post(f"{API_URL}/upload", headers=headers(),
                                  files={"file": (up.name, up.getvalue())}, timeout=120)
                if r.ok:
                    n = r.json().get("chunks_indexed", 0)
                    st.session_state.uploaded.append(up.name)
                    st.success(f"{up.name} · {n} chunks")
                else:
                    st.error(f"Upload failed: {r.text[:200]}")
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not reach API: {e}")
    for name in st.session_state.uploaded:
        st.caption(f"✅ {name}")

    # --- quality & internals live here, in the sidebar, behind an expander ---
    st.divider()
    with st.expander("📊 Quality & internals"):
        try:
            q = requests.get(f"{API_URL}/quality", headers=headers(), timeout=10).json()
            if q.get("available"):
                st.markdown("**Evaluation**")
                st.caption(f"Correctness {q['avg_correctness']:.2f} · "
                           f"Faithfulness {q['avg_faithfulness']:.2f} · "
                           f"Pass {q['pass_rate']*100:.0f}%")
                if q.get("gate_passed"):
                    st.success(f"CI gate: PASS · {q.get('cases')} cases")
                else:
                    st.error("CI gate: FAIL")
                st.caption(f"{q.get('model')} · prompt {q.get('prompt_version')}")
            else:
                st.caption("No eval runs yet.")
        except Exception:  # noqa: BLE001
            st.caption("Quality endpoint unavailable.")

        st.markdown("**Observability**")
        try:
            m = requests.get(f"{API_URL}/metrics", headers=headers(), timeout=10).json()
            if m.get("runs"):
                st.caption(f"{m['runs']} runs · {m['avg_latency_ms']:.0f} ms avg · "
                           f"${m['total_cost_usd']:.4f} total · "
                           f"{m['error_rate']*100:.0f}% errors")
            else:
                st.caption("No runs yet.")
            tr = requests.get(f"{API_URL}/traces", headers=headers(), timeout=10).json()
            traces = tr.get("traces", [])
            for t in traces[:5]:
                st.caption(
                    f"`{t['trace_id'][:10]}` · {t['total_ms']:.0f} ms · "
                    f"{t['tool_calls']} tools · ${t['cost_usd']:.4f}"
                )
        except Exception:  # noqa: BLE001
            st.caption("Observability unavailable.")

    st.divider()
    st.caption(f"Session: `{st.session_state.session_id}`")


# --- main: just the chat --------------------------------------------------
st.title("Ask anything")
st.caption("General questions use web search. Upload a document to ground answers. "
           "Destructive file actions pause for your approval.")

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("badges"):
            st.caption(" · ".join(m["badges"]))

if st.session_state.pending:
    p = st.session_state.pending
    tool = p["tool"]
    args = tool.get("arguments", {})
    with st.chat_message("assistant"):
        st.warning(f"🛡️ **Approval needed** — the agent wants to run `{tool.get('name')}`.")
        if args:
            st.markdown("**Proposed action:**")
            st.json(args)
        col1, col2 = st.columns(2)
        approve_clicked = col1.button("✅ Approve", use_container_width=True, key="approve_btn")
        reject_clicked = col2.button("❌ Reject", use_container_width=True, key="reject_btn")

    if approve_clicked or reject_clicked:
        decision = "approve" if approve_clicked else "reject"
        with st.spinner(f"Sending {decision}…"):
            try:
                r = requests.post(f"{API_URL}/approve", headers=headers(),
                                  json={"approval_id": p["run_id"], "decision": decision},
                                  timeout=180)
                data = r.json()
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not reach API: {e}")
                st.stop()
        store_result(data)
        st.rerun()

prompt = st.chat_input("Ask a question…", disabled=bool(st.session_state.pending))
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.spinner("Agent working…"):
        try:
            r = requests.post(f"{API_URL}/ask", headers=headers(),
                              json={"question": prompt, "docs_only": docs_only}, timeout=180)
            data = r.json()
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not reach API: {e}")
            st.stop()
    store_result(data)
    st.rerun()