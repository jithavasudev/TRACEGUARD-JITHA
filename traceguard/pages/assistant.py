import re
import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import db, rules
from auth import require_login

require_login()
st.title("💬 AML Assistant")
st.caption("Answers from the rule documentation and your alert data. Try: “Why was transaction 123 flagged?”, "
           "“What is a mule account?”, “What does fan-in mean?”, “How is the risk score calculated?”")

SYNONYMS = {
    "Mule pass-through": "mule money mule mule account pass through passthrough forwarded onward cash-out",
    "Fan-in": "fan in collector many senders victims collecting",
    "Fan-out": "fan out distributor spreading many receivers",
    "Dormant account active": "dormant inactive sleeping old account takeover",
    "Shared device": "device sharing same phone handset operator",
    "Shared IP": "ip address network same ip",
    "Structuring": "smurfing threshold just below reporting",
    "High velocity": "velocity many transactions rapid frequency",
    "Statistical outlier": "outlier z-score unusual amount deviation",
    "network ring": "ring network cluster graph connected accounts trace",
    "risk score": "score calculated weights alert threshold",
    "false positive": "false positives precision feedback",
}
def norm(t):
    t = re.sub(r"fan[\s-]*in\b", "fanin", t.lower())
    return re.sub(r"fan[\s-]*out\b", "fanout", t)


names, docs = list(rules.RULE_DOCS), list(rules.RULE_DOCS.values())
index_text = [norm(f"{n} {n} {SYNONYMS.get(n, '')} {d}") for n, d in zip(names, docs)]
vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2)).fit(index_text)
mat = vec.transform(index_text)


def explain_tx(tx_id):
    df = db.query("SELECT * FROM transactions WHERE id=?", (tx_id,))
    if df.empty:
        return f"I could not find transaction {tx_id}."
    t = df.iloc[0]
    out = [f"**Transaction {tx_id}**: {t.sender} → {t.receiver}, amount {t.amount:,.2f} on {t.tx_date}.",
           f"Rule score {t.rule_score}, ML score {t.ml_score}, final risk score **{t.risk_score}** "
           f"({'flagged' if t.flagged else 'not flagged'})."]
    for r in str(t.reasons or "").split("; "):
        if r:
            out.append(f"- **{r}**  \n  _{rules.RULE_DOCS.get(r.split(':')[0].strip(), '')}_")
    if not t.reasons:
        out.append("No rule fired and the ML score was not high enough to give a reason.")
    return "\n".join(out)


def answer(msg):
    m = re.search(r"\b(\d+)\b", msg)
    if m and re.search(r"transaction|flag|why|alert", msg, re.I):
        return explain_tx(int(m.group(1)))
    sims = cosine_similarity(vec.transform([norm(msg)]), mat)[0]
    if sims.max() < 0.05:
        return ("I only know the rules in this app. Ask about structuring, velocity, fan-in, fan-out, mule accounts, "
                "dormant accounts, shared devices, the risk score, network rings or false positives.")
    return f"**{names[sims.argmax()]}**\n\n{docs[sims.argmax()]}"


st.session_state.setdefault("chat", [])
for role, text in st.session_state.chat:
    st.chat_message(role).markdown(text)
if prompt := st.chat_input("Ask about a rule or a transaction"):
    st.session_state.chat += [("user", prompt), ("assistant", answer(prompt))]
    st.rerun()
