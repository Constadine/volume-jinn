import os, streamlit as st, pandas as pd
from dotenv import load_dotenv
import tools   # ← the helper functions you already have

load_dotenv()

# ── 1. Ask for the key (once per browser session) ──────────────────────────────
if "hevy_key" not in st.session_state:
    st.session_state.hevy_key = ""        # initialise the variable

with st.sidebar:                          # sidebar keeps the main UI clean
    st.markdown("### 🔑 Hevy API Key")
    with st.form(key="key_form", clear_on_submit=False):
        key_input = st.text_input(
            "Paste your personal key here",
            type="password",              # masks the characters
            placeholder="1a...",
        )
        submit = st.form_submit_button("Use this key")

        if submit:
            st.session_state.hevy_key = key_input.strip()
            if st.session_state.hevy_key:
                st.success("Key stored for **this session** only.")
            else:
                st.warning("No key entered – you’ll need one to proceed.")

apikey = st.session_state.hevy_key or os.getenv("HEVY_API_KEY", "")

# ── 2. Refuse to proceed without a key ─────────────────────────────────────────
if not apikey:
    st.stop()     # the sidebar prompt stays visible; nothing else renders


st.title("Volume Jinn 🧞")

# Optional: let the user decide which previous workout to pull
workout_title = st.text_input("Workout Title (blank = most recent)")

if apikey is None:
    st.error("Environment variable HEVY_API_KEY not found"); st.stop()

# Grab the workout and tidy it up
raw_wk   = tools.fetch_last_workout(apikey, workout_title)
if not raw_wk:
    st.warning("No workout found."); st.stop()

exercises = tools.structure_workout_data(raw_wk)

st.header(raw_wk["title"])
vol_bump_pct = st.slider("Volume increase target (%)", 0, 30, 5, step=1) / 100

# ──-- One expander per exercise --──
for ex in exercises:
    name          = ex["exercise"]
    original_sets = ex["sets"]           # list[(reps, kg)]
    opts = tools.get_optimized_options(
        {"exercise": name, "sets": original_sets},
        volume_perc = vol_bump_pct          # e.g. +5 %
    )
    plan_sets    = opts["final_sets"]       # [(reps, kg), …] sized & bumped
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

        # 2️⃣ compute volumes ----------------------------------------------
        current_vol = int((edited_df["reps"] * edited_df["kg"]).sum())
        pct_of_goal = current_vol / target_vol if target_vol else 0

        # 3️⃣ visuals -------------------------------------------------------
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
            st.write(opts["phases"])      # phase-by-phase bump logic
