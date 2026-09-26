"""The Ask page: plain-English questions about every match in the stats database."""

from __future__ import annotations

import altair as alt
import streamlit as st

from ask_engine import Answer, Vocab, ask, suggestions
from metrics_engine import rows_csv
from sources import current_source, open_stats_db, sync_with_progress
from stats_db import nice_day
from ui import DEFAULT_ACCENT, md

_FORMATS = {"ratio": "%.2f", "pct": "%.0f%%", "eps": "%d", "count": "%d", "signed": "%+d"}
_CHART_FORMATS = {"ratio": ".2f", "pct": ".0f", "eps": "d", "count": "d", "signed": "+d"}
MUTED = "#83a99c"  # the page's mint (app.py)


def _set_question(text: str) -> None:
    st.session_state["ask_question"] = text
    st.session_state["ask_now"] = True


def _chart(answer: Answer, me: str | None) -> None:
    """The answer as a chart, in the table's order (matches oldest first, rankings best first), with
    your own bar picked out in a ranking of players."""
    x, y = answer.chart["x"], answer.chart["y"]
    data = [{"x": r[x], "y": r[y]} for r in answer.rows if r.get(y) is not None]
    number = _CHART_FORMATS.get(answer.formats.get(y, ""), "")
    chart = alt.Chart(alt.Data(values=data)).encode(
        x=alt.X("x:N", sort=None, title=None, axis=alt.Axis(labelAngle=-35, labelLimit=180)),
        y=alt.Y("y:Q", title=y, axis=alt.Axis(format=number)),
        tooltip=[alt.Tooltip("x:N", title=x), alt.Tooltip("y:Q", title=y, format=number)],
    )
    if answer.chart["kind"] == "line":
        chart = chart.mark_line(point=True, color=DEFAULT_ACCENT)
    else:
        chart = chart.mark_bar().encode(color=alt.condition(alt.datum.x == (me if x == "Player" else None),
                                                            alt.value(DEFAULT_ACCENT), alt.value(MUTED)))
    st.altair_chart(chart.properties(height=260), width="stretch")


st.title("Ask")
st.caption("Ask anything about your matches in plain English: trends, maps, operators, teammates, "
           "your team. Everything stays on this computer.")

with open_stats_db() as db:
    source = current_source()
    if source and "error" not in source:
        sync_with_progress(db, source)
    summary = db.summary()
    if not summary["matches"]:
        st.info("No matches yet. Open your replays on **Dashboard** (or upload them there), and they'll "
                "show up here.")
        st.stop()
    vocab = Vocab.from_db(db)
    me = vocab.players.get(vocab.me) if vocab.me else None
    st.caption(f"📚 {summary['matches']} matches, {nice_day(summary['first'])} to {nice_day(summary['last'])}"
               + (f" · you're **{md(me)}**" if me else ""))

    with st.form("ask_form", border=False):
        question = st.text_input("Your question", key="ask_question", label_visibility="collapsed",
                                 placeholder="e.g. How has my K/D changed over my last 10 matches?")
        asked = st.form_submit_button("Ask", type="primary")
    examples = suggestions(vocab, db)
    columns = st.columns(4)
    for i, example in enumerate(examples):
        columns[i % 4].button(example, key=f"example_{i}", on_click=_set_question, args=(example,),
                              width="stretch")

    if (asked or st.session_state.pop("ask_now", False)) and question.strip():
        st.session_state["ask_last"] = question.strip()
    last = st.session_state.get("ask_last")
    if last:
        answer = ask(last, db, vocab=vocab)
        st.divider()
        if answer.understood:
            st.caption(f"🔎 {md(answer.understood)}")
        if answer.ok:
            st.markdown(f"#### {md(answer.headline)}")
        else:
            st.warning(md(answer.headline), icon="💬")
        for note in answer.notes:
            st.caption(md(note))
        if answer.ok and answer.chart and len(answer.rows) > 1:
            _chart(answer, me)
        if answer.ok and answer.rows:
            config = {c: st.column_config.NumberColumn(format=_FORMATS[k]) for c, k in answer.formats.items()}
            st.dataframe(answer.rows, column_order=answer.columns, column_config=config, hide_index=True)
            st.download_button("⬇ CSV", rows_csv(answer.rows).encode("utf-8"), file_name="r6_answer.csv",
                               mime="text/csv")
