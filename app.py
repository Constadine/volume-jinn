
import os
from datetime import datetime
import copy
from typing import List, Dict

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from hevy import Hevy
from datatypes import ExerciseData

load_dotenv()

st.set_page_config(page_title="Volume Jinn", page_icon="🧞")

# ────────────────────────────────────────────────────────────────────────────
# 🔑 0.  API‑key handling (stored only in this browser session)
# ────────────────────────────────────────────────────────────────────────────
if "hevy_key" not in st.session_state:
    st.session_state.hevy_key = ""

with st.sidebar:
    st.markdown("### 🔑 Hevy API Key")
    with st.form("key_form", clear_on_submit=False):
        key_input = st.text_input("Gimme your key", type="password", placeholder="Paste on me…")
        if st.form_submit_button("Use this key"):
            st.session_state.hevy_key = key_input.strip()
            if st.session_state.hevy_key:
                st.success("Key stored for **this session** only.")
            else:
                st.warning("No key entered - you'll need one to proceed.")

apikey = st.session_state.hevy_key or os.getenv("HEVY_API_KEY", "")
hevy   = Hevy(apikey=apikey)

if not apikey:
    st.info("Enter your personal Hevy API key in the sidebar to load a workout. Your key is stored **only in this browser session** and never logged.")
    st.stop()

# ────────────────────────────────────────────────────────────────────────────
st.title("Volume Jinn 🧞")

# ───────────────────────────────── SIDEBAR INPUTS ────────────────────────────
with st.sidebar:
    search_by = st.radio("Search by", ["Workout", "Exercise"])

    if search_by == "Workout":
        workout_title = st.selectbox("Workout Title (leave empty for most recent)", options=sorted(hevy.get_all_workouts()), index=None, placeholder="(Latest workout)")
    else:
        exercise_titles = st.multiselect("Exercise Title", options=sorted(hevy.get_all_exercises()))

    vol_bump_pct = st.slider("Volume increase target (%)", 0, 20, 5, 1) / 100

    baseline_source = st.radio("Baseline session volume", ["First session", "Last session"], help=("*First session*: Each new workout adds a **constant** volume equal to (first_session_volume × bump %).\n*Last session*: Classic multiplicative progression (last × bump %)."))

# ─────────────────────────────── DATA FETCH ─────────────────────────────────
if search_by == "Workout":
    try:
        raw_wk = hevy.fetch_last_workout(workout_title or None)
    except Exception as err:
        st.error(f"API error: {err}")
        st.stop()

    if not raw_wk:
        st.warning("No workout found with that title.")
        st.stop()

    exercises = hevy.structure_workout_data(raw_wk)
    # Prefer the workout’s *performed* timestamp; fall back to creation time
    event_ts = raw_wk.get("performed_at") or raw_wk["created_at"]
    event_dt = datetime.fromisoformat(event_ts.replace("Z", "+00:00"))
    # date/time of the chosen baseline session
    if baseline_source == "First session":
        first_wk = hevy.fetch_first_workout(workout_title or None)
        base_ts  = (first_wk.get("performed_at") if first_wk else None) or (first_wk.get("created_at") if first_wk else event_ts)
    else:  # baseline = last session (same as current)
        base_ts = event_ts
    base_dt = datetime.fromisoformat(base_ts.replace("Z", "+00:00"))

    st.header(
        f"{raw_wk['title']} · {event_dt:%B %d, %Y – %H:%M} | Baseline: {base_dt:%B %d, %Y}"
    )

else:
    if not exercise_titles:
        st.info("👈 Pick at least one exercise to continue.")
        st.stop()

    exercises: List[ExerciseData] = []
    missing:   List[str] = []

    for title in exercise_titles:
        try:
            raw_ex = hevy.get_exercise_last_data(title)
            if raw_ex and not raw_ex.get("error"):
                exercises.append(hevy.structure_exercise_data(raw_ex))
            else:
                missing.append(title)
        except Exception as err:
            st.error(f"API error while fetching **{title}** – {err}")
            st.stop()

    if not exercises:
        st.warning("No recent data found for the selected exercise(s).")
        st.stop()

    if missing:
        st.warning("No recent session found for: " + ", ".join(missing))

    hdr = ", ".join(exercise_titles) if len(exercise_titles) <= 3 else f"{len(exercise_titles)} exercises"
    st.header(f"Last session · {hdr}")

# ──────────────────────────── UTILITY FUNCTIONS ─────────────────────────────

def calc_volume(sets):
    return sum((s.get("weight_kg", 0) or 0) * (s.get("reps", 0) or 0) for s in sets)


def simple_increment_plan(original_sets, target_volume):
    plan = copy.deepcopy(original_sets)
    for s in plan:
        s["reps"] = int(s.get("reps", 0))
        s["weight_kg"] = s.get("weight_kg") or 0
    guard = 0
    while calc_volume(plan) < target_volume and guard < 200:
        idx = max(range(len(plan)), key=lambda i: plan[i]["weight_kg"])
        plan[idx]["reps"] += 1
        guard += 1
    return plan

# ──────────────────────── CACHED FIRST‑VOL LOOKUP ───────────────────────────

@st.cache_data(show_spinner=False)
def get_first_vol_map(names: tuple) -> Dict[str, int]:
    """Return {exercise → first‑session volume} with one API sweep per rerun."""
    vol_map = {}
    for n in names:
        first_data = hevy.get_first_exercise_data(n)
        vol_map[n] = calc_volume(first_data["sets"]) if first_data else None
    return vol_map

first_vol_map = get_first_vol_map(tuple(e["exercise"] for e in exercises)) if baseline_source == "First session" else {}

# ───────────────────────────── MAIN LOOP ────────────────────────────────────
for ex in exercises:
    name          = ex["exercise"]
    original_sets = ex["sets"]
    last_vol      = ex["volume"] or 1

    # ── baseline + targets --------------------------------------------------
    if baseline_source == "First session":
        baseline_vol = first_vol_map.get(name) or last_vol
        absolute_increment = baseline_vol * vol_bump_pct
        target_vol         = last_vol + absolute_increment
    else:
        baseline_vol       = last_vol
        target_vol         = last_vol * (1 + vol_bump_pct)
        absolute_increment = target_vol - last_vol

    effective_bump_pct = max((target_vol / last_vol) - 1, 0)

    # ── plan generation -----------------------------------------------------
    try:
        opts      = hevy.get_optimized_options({"exercise": name, "sets": original_sets}, volume_perc=effective_bump_pct)
        plan_sets = opts.get("final_sets") or original_sets
        reasoning = opts.get("phases", "(no optimiser output)")
    except Exception:
        plan_sets = simple_increment_plan(original_sets, target_vol)
        reasoning = "Fallback heuristic plan (Hevy optimiser failed)"

    # ── UI ------------------------------------------------------------------
    with st.expander(name, expanded=True):
        preset = st.radio("Start the editor with…", ["Last session", "Optimised plan"], horizontal=True, key=f"preset_{name}")

        df_default = plan_sets if preset == "Optimised plan" else original_sets
        df         = pd.DataFrame(df_default, columns=["reps", "kg"])
        edited_df  = st.data_editor(df, num_rows="dynamic", key=f"de_{name}")

        current_vol = int((edited_df["reps"] * edited_df["kg"]).sum())
        diff_vol    = target_vol - current_vol
        pct_of_goal = current_vol / target_vol if target_vol else 0

        cols = st.columns(3)
        cols[0].metric("Baseline vol", int(baseline_vol))
        cols[1].metric("Target vol", int(target_vol))
        cols[2].metric("Current vol", current_vol, delta=f"{round(diff_vol,1):+} vol")

        st.progress(min(pct_of_goal, 1.0), text=f"{current_vol} / {int(target_vol)} vol")

        if diff_vol > 0:
            st.write(f"⬆️ Add {(diff_vol)} vol more to hit your target.")
        elif diff_vol < 0:
            st.write(f"✅ Surpassed target by {abs(diff_vol)} vol")
        else:
            st.write("🎉 Damn exactly.")

        with st.expander("Optimiser phases / reasoning"):
            st.write(reasoning)
