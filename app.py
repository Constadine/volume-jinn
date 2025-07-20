import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from hevy import Hevy
from datatypes import ExerciseData

load_dotenv()

st.set_page_config(page_title="Volume Jinn", page_icon="🧞")

# ── 1. Ask for the key (once per browser session) ──────────────────────────────
if "hevy_key" not in st.session_state:
    st.session_state.hevy_key = ""

with st.sidebar:
    st.markdown("### 🔑 Hevy API Key")
    with st.form(key="key_form", clear_on_submit=False):
        key_input = st.text_input(
            "Gimme your key",
            type="password",              # masks the characters
            placeholder="1a...",
        )
        submit = st.form_submit_button("Use this key")

        if submit:
            st.session_state.hevy_key = key_input.strip()
            if st.session_state.hevy_key:
                st.success("Key stored for **this session** only.")
            else:
                st.warning("No key entered - you'll need one to proceed.")

apikey = st.session_state.hevy_key or os.getenv("HEVY_API_KEY", "")
hevy = Hevy(apikey=apikey)


# ── 2. Refuse to proceed without a key ─────────────────────────────────────────
if not apikey:
    st.info(
        "Enter your personal Hevy API key in the sidebar to load a workout. "
        "Your key is stored **only in this browser session** and never logged."
    )
    st.stop()     # the sidebar prompt stays visible; nothing else renders


st.title("Volume Jinn 🧞")

# Optional: let the user decide which previous workout to pull

if apikey is None:
    st.error("Environment variable HEVY_API_KEY not found")
    st.stop()

# ───────────────────────── SIDEBAR ──────────────────────────
with st.sidebar:
    search_by = st.radio("Search by", ["Workout", "Exercise"])
    if search_by == "Workout":
        all_workouts = hevy.get_all_workouts()
        workout_title = st.selectbox(
            "Workout Title (leave empty for most recent)",
            options=sorted(hevy.get_all_workouts()),
            index=None,
            placeholder="(Latest workout)"
        )

        raw_wk = hevy.fetch_last_workout(workout_title or None)
    else:  # Exercise
        all_exercises = hevy.get_all_exercises()
        exercise_titles = st.multiselect(
            "Exercise Title",
            options=sorted(all_exercises),
            default=None
        )

    vol_bump_pct = st.slider(
        "Volume increase target (%)",
        0, 20, 5, step=1
    ) / 100
# ────────────────────────────────────────────────────────────


# ──────────────── FETCH & STRUCTURE DATA ───────────────────
if search_by == "Workout":
    # pull the most-recent workout of that title (or latest overall)
    try:
        raw_wk = hevy.fetch_last_workout(
            workout_title or None          # "" → None for “latest”
        )
        if not raw_wk:
            st.warning("No workout found with that title.")
            st.stop()
    except Exception as err:
        st.error(f"⚠️ Could not fetch workout - {err}")
        st.stop()

    exercises = hevy.structure_workout_data(raw_wk)

    # pretty header with workout time
    created_at = datetime.fromisoformat(
        raw_wk["created_at"].replace("Z", "+00:00")
    )
    st.header(f'{raw_wk["title"]} · {created_at:%B %d, %Y – %H:%M}')

else:  # Exercise mode
    # 1 nothing chosen yet → ask the user and stop early
    if not exercise_titles:
        st.info("👈 Pick at least one exercise to continue.")
        st.stop()

    # 2 pull each exercise’s last-session data
    exercises: list[ExerciseData] = []
    missing:   list[str]  = []

    for title in exercise_titles:
        try:
            raw_ex = hevy.get_exercise_last_data(title)
        except Exception as err:
            st.error(f"API error while fetching **{title}** – {err}")
            st.stop()

        if not raw_ex or raw_ex.get("error"):
            missing.append(title)
            continue

        exercises.append(hevy.structure_exercise_data(raw_ex))

    # 3 if none of the chosen items came back with data
    if not exercises:
        st.warning("No recent data found for the selected exercise(s).")
        st.stop()

    # 4 tell me which ones were skipped
    if missing:
        st.warning("No recent session found for: " + ", ".join(missing))

    # 5 header
    st.header(
        "Last session · " +
        (", ".join(exercise_titles) if len(exercise_titles) <= 3 else
         f"{len(exercise_titles)} exercises")
    )


# ────────────────────────────────────────────────────────────


# ──-- One expander per exercise --──
for ex in exercises:
    name          = ex["exercise"]
    original_sets = ex["sets"]
    opts = hevy.get_optimized_options(
        {"exercise": name, "sets": original_sets},
        volume_perc = vol_bump_pct          # e.g. +5 %
    )
    plan_sets    = opts["final_sets"]
    target_vol   = int(opts["target_volume"])
    baseline_vol = int(ex["volume"])        # what I lifted last time

    with st.expander(name, expanded=True):
        preset = st.radio(
            "Start the editor with…",
            ["Optimised plan", "Last session"],
            horizontal=True,
            key=f"preset_{name}"
        )

        # default rows → either the plan or the old sets
        default_rows = plan_sets if preset == "Optimised plan" else original_sets
        df  = pd.DataFrame(default_rows, columns=["reps", "kg"])

        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            key=f"de_{name}"
        )

        # 2 compute volumes ----------------------------------------------
        current_vol = int((edited_df["reps"] * edited_df["kg"]).sum())
        pct_of_goal = current_vol / target_vol if target_vol else 0

        # 3 visuals -------------------------------------------------------
        col1, col2 = st.columns(2)
        col1.metric("Baseline vol", int(baseline_vol))
        col2.metric("Current vol",  current_vol,
                    delta=f"{pct_of_goal*100:.1f}% of target")

        st.progress(min(pct_of_goal, 1.0),
                    text=f"{current_vol} / {int(target_vol)} kg·reps")

        if current_vol >= target_vol:
            st.success("🎯 Target volume reached!")
        elif pct_of_goal >= 0.9:
            st.info("⬆️ Almost there – one more rep or a tiny weight bump!")

        with st.expander("Optimiser phases / reasoning"):
            st.write(opts["phases"])
