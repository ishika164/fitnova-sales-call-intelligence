"""
FitNova Call Intelligence Dashboard.

Three role views, because the brief explicitly names three different
audiences with different needs:
  - Sales Director: org-wide health, team comparison, trend
  - Team Leader: their team's advisors, worst-scoring calls to coach on
  - Advisor: their own calls, their own flags, and the ability to contest one

Run: streamlit run dashboard/app.py
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import pandas as pd
from src.models import get_session, Org, Team, Advisor, Call, CallScore, IssueFlag, FlagContest

st.set_page_config(page_title="FitNova Call Intelligence", layout="wide")

DIMS = ["needs_discovery", "product_knowledge", "objection_handling", "compliance", "next_step_booking"]


@st.cache_resource
def get_db_session():
    return get_session("data/fitnova.db")


def load_calls_df(session):
    calls = session.query(Call).filter(Call.status == "done").all()
    rows = []
    for c in calls:
        rows.append({
            "call_id": c.id,
            "advisor": c.advisor.name if c.advisor else "Unknown",
            "team": c.advisor.team.name if c.advisor and c.advisor.team else "Unknown",
            "date": c.call_datetime,
            "is_sales_call": c.is_sales_call,
            "overall_score": c.score.overall_score if c.score else None,
            "num_flags": len(c.flags),
            "high_severity_flags": sum(1 for f in c.flags if f.severity == "high"),
            "diarization_note": c.diarization_method or "unknown",
            "source_ref": c.source_ref,
        })
    return pd.DataFrame(rows)


def render_sales_director(session, df):
    st.header("Sales Director — Org Health")
    sales_df = df[df.is_sales_call == True]
    if sales_df.empty:
        st.warning("No scored sales calls yet. Run the pipeline first.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total calls analyzed", len(df))
    col2.metric("Org avg score", f"{sales_df.overall_score.mean():.1f} / 10")
    col3.metric("Calls with flags", int((sales_df.num_flags > 0).sum()))
    col4.metric("High-severity flags", int(sales_df.high_severity_flags.sum()))

    st.subheader("Score by team")
    team_avg = sales_df.groupby("team").overall_score.mean().reset_index()
    st.bar_chart(team_avg.set_index("team"))

    st.subheader("All calls")
    st.dataframe(sales_df.sort_values("overall_score"), use_container_width=True)


def render_team_leader(session, df):
    st.header("Team Leader — Coach Your Team")
    teams = sorted(df.team.unique())
    if not teams:
        st.warning("No data yet.")
        return
    team = st.selectbox("Select team", teams)
    team_df = df[(df.team == team) & (df.is_sales_call == True)]

    st.subheader(f"{team} — advisor averages")
    adv_avg = team_df.groupby("advisor").overall_score.mean().reset_index().sort_values("overall_score")
    st.bar_chart(adv_avg.set_index("advisor"))

    st.subheader("Calls to review (lowest scores / most flags first)")
    review_df = team_df.sort_values(["overall_score", "high_severity_flags"], ascending=[True, False])
    st.dataframe(review_df, use_container_width=True)

    st.subheader("Flag review & contest resolution")
    render_flag_review(session, team_df.call_id.tolist())


def render_advisor(session, df):
    st.header("Advisor — My Calls")
    advisors = sorted(df.advisor.unique())
    if not advisors:
        st.warning("No data yet.")
        return
    advisor = st.selectbox("Select advisor (login stand-in for this prototype)", advisors)
    my_df = df[(df.advisor == advisor) & (df.is_sales_call == True)]

    if my_df.empty:
        st.info("No scored calls for this advisor yet.")
        return

    col1, col2 = st.columns(2)
    col1.metric("My average score", f"{my_df.overall_score.mean():.1f} / 10")
    col2.metric("My flagged calls", int((my_df.num_flags > 0).sum()))

    st.subheader("My calls")
    st.dataframe(my_df, use_container_width=True)

    st.subheader("My flags — contest one if you think it's unfair")
    render_flag_contest_ui(session, my_df.call_id.tolist())


def render_flag_review(session, call_ids):
    flags = session.query(IssueFlag).filter(IssueFlag.call_id.in_(call_ids)).all()
    if not flags:
        st.info("No flags on this team's calls.")
        return
    for flag in flags:
        with st.expander(f"[{flag.severity.upper()}] {flag.tag} — Call #{flag.call_id} — status: {flag.status}"):
            st.write(f"**Quoted line:** \"{flag.quoted_line}\"")
            st.write(f"**Reason:** {flag.reason}")
            st.write(f"**Timestamp:** {flag.timestamp:.1f}s")
            if flag.contest:
                st.write(f"**Advisor contest:** {flag.contest.advisor_comment}")
                resolution = st.selectbox(
                    "Resolve contest", ["pending", "upheld", "dismissed"],
                    index=["pending", "upheld", "dismissed"].index(flag.contest.resolution),
                    key=f"resolve_{flag.id}",
                )
                if st.button("Save resolution", key=f"save_{flag.id}"):
                    flag.contest.resolution = resolution
                    flag.status = "upheld" if resolution == "upheld" else "dismissed" if resolution == "dismissed" else "contested"
                    session.commit()
                    st.success("Saved.")
                    st.rerun()


def render_flag_contest_ui(session, call_ids):
    flags = session.query(IssueFlag).filter(IssueFlag.call_id.in_(call_ids)).all()
    if not flags:
        st.info("No flags on your calls. Nice work.")
        return
    for flag in flags:
        label = f"[{flag.severity.upper()}] {flag.tag} — Call #{flag.call_id}"
        with st.expander(label):
            st.write(f"**Quoted line:** \"{flag.quoted_line}\"")
            st.write(f"**Reason given:** {flag.reason}")
            st.write(f"**Status:** {flag.status}")
            if flag.contest:
                st.info(f"Already contested: \"{flag.contest.advisor_comment}\" (resolution: {flag.contest.resolution})")
            else:
                comment = st.text_area("Why is this flag unfair?", key=f"contest_text_{flag.id}")
                if st.button("Contest this flag", key=f"contest_btn_{flag.id}"):
                    if comment.strip():
                        session.add(FlagContest(flag_id=flag.id, advisor_comment=comment))
                        flag.status = "contested"
                        session.commit()
                        st.success("Contest submitted — your Team Leader will review it.")
                        st.rerun()
                    else:
                        st.error("Add a reason before submitting.")


def main():
    st.title("🏋️ FitNova Call Intelligence")
    session = get_db_session()
    df = load_calls_df(session)

    role = st.sidebar.radio("View as", ["Sales Director", "Team Leader", "Advisor"])
    st.sidebar.caption("Role switcher stands in for real auth/login in this prototype.")

    if role == "Sales Director":
        render_sales_director(session, df)
    elif role == "Team Leader":
        render_team_leader(session, df)
    else:
        render_advisor(session, df)


if __name__ == "__main__":
    main()
