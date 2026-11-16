import re
import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import db, rules
from auth import require_login

require_login()
st.title("💬 AML Assistant")
st.caption("Answers from your AML rule documentation and alert data. Ask: “Why was transaction 123 flagged?”, "
           "“What is structuring?”, “How is the risk score calculated?”")

names, docs = list(rules.RULE_DOCS), list(rules.RULE_DOCS.values())
vec = TfidfVectorizer(stop_words="english").fit(docs)
mat = vec.transform(docs)


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
            key = r.split(":")[0].strip()
            out.append(f"- **{r}**  \n  _{rules.RULE_DOCS.get(key, '')}_")
    if not t.reasons:
        out.append("No rule fired and the ML score was not high enough to give a reason.")
    return "\n".join(out)


def answer(msg):
    m = re.search(r"\b(\d+)\b", msg)
    if m and re.search(r"transaction|flag|why|alert", msg, re.I):
        return explain_tx(int(m.group(1)))
    sims = cosine_similarity(vec.transform([msg]), mat)[0]
    if sims.max() < 0.05:
        return "I only know the AML rules in this app. Try asking about structuring, velocity, outliers, high-risk countries, risk score or false positives."
    return f"**{names[sims.argmax()]}**\n\n{docs[sims.argmax()]}"


if "chat" not in st.session_state:
    st.session_state.chat = []
for role, text in st.session_state.chat:
    st.chat_message(role).markdown(text)
if prompt := st.chat_input("Ask about a rule or a transaction"):
    st.session_state.chat.append(("user", prompt))
    st.session_state.chat.append(("assistant", answer(prompt)))
    st.rerun()
