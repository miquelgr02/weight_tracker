import copy
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit_authenticator as stauth
from streamlit_gsheets import GSheetsConnection

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Bulking Dashboard", layout="wide")

# --- AUTHENTICATION SETUP ---
secrets_dict = st.secrets.to_dict()
credentials = copy.deepcopy(secrets_dict["credentials"])
cookie = secrets_dict["cookie"]

authenticator = stauth.Authenticate(
    credentials, cookie["name"], cookie["key"], cookie["expiry_days"]
)
authenticator.login()

if st.session_state.get("authentication_status"):
    authenticator.logout("Logout", "sidebar")
    conn = st.connection("gsheets", type=GSheetsConnection)

    @st.cache_data(ttl=600)
    def fetch_data():
        data = conn.read(worksheet="Sheet1")
        data = data.dropna(how="all")
        data["Date"] = pd.to_datetime(data["Date"])
        # We return OLDEST first here so rolling averages calculate correctly
        return data.sort_values(by="Date", ascending=True)

    # Base data (Oldest to Newest)
    df = fetch_data()

    # --- SIDEBAR CONTROLS ---
    with st.sidebar:
        st.header("Settings")
        window = st.slider("Rolling Average Window (Days)", 1, 30, 7)

        st.divider()
        st.header("Log New Entry")
        with st.form("weight_form", clear_on_submit=True):
            entry_date = st.date_input("Date", value=datetime.today())
            entry_weight = st.number_input(
                "Weight (kg)", min_value=30.0, max_value=200.0, step=0.1
            )
            submit_button = st.form_submit_button("Submit Entry")

        if submit_button:
            try:
                raw_data = conn.read(worksheet="Sheet1", ttl=0)
                current_df = (
                    raw_data.dropna(how="all")
                    if raw_data is not None
                    else pd.DataFrame(columns=["Date", "Weight"])
                )

                new_row = pd.DataFrame(
                    [
                        {
                            "Date": entry_date.strftime("%Y-%m-%d"),
                            "Weight": float(entry_weight),
                        }
                    ]
                )

                # Combine and sort DESCENDING so the Google Sheet itself has newest on top
                final_df = pd.concat([current_df, new_row], ignore_index=True)
                final_df["Date"] = pd.to_datetime(final_df["Date"])
                final_df = final_df.drop_duplicates(subset=["Date"], keep="last")
                final_df = final_df.sort_values(by="Date", ascending=False)
                final_df["Date"] = final_df["Date"].dt.strftime("%Y-%m-%d")

                conn.update(worksheet="Sheet1", data=final_df)
                st.success("Weight logged!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    # --- DATA PROCESSING ---
    if not df.empty:
        # 1. Calculate Rolling Avg on Ascending data (Correct Math)
        df["Rolling_Avg"] = df["Weight"].rolling(window=window).mean()

        # 2. Create the display version (Newest to Oldest)
        display_df = df.sort_values(by="Date", ascending=False).copy()

        # 3. Weekly Stats
        weekly_df = (
            df.resample("W-SUN", on="Date").mean(numeric_only=True).reset_index()
        )

        tab1, tab2 = st.tabs(["📈 Dashboard", "⚙️ Edit Data"])

        # --- TAB 1: DASHBOARD ---
        with tab1:
            st.title("Weight Dashboard")
            m1, m2, m3 = st.columns(3)

            # Latest values are now at index 0 of display_df
            latest_weight = display_df.iloc[0]["Weight"]
            latest_rolling = display_df.iloc[0]["Rolling_Avg"]
            total_gained = latest_weight - display_df.iloc[-1]["Weight"]

            m1.metric("Current", f"{latest_weight:.1f} kg")
            m2.metric(
                f"{window}-Day Avg",
                f"{latest_rolling:.2f} kg" if pd.notna(latest_rolling) else "N/A",
            )
            m3.metric("Total Progress", f"{total_gained:+.1f} kg")

            # Chart (Plotly needs chronological order to draw lines correctly)
            fig_trend = go.Figure()
            fig_trend.add_trace(
                go.Scatter(
                    x=df["Date"],
                    y=df["Weight"],
                    mode="markers",
                    name="Daily Weight",
                    marker=dict(color="rgba(255, 255, 255, 0.2)", size=6),
                )
            )
            fig_trend.add_trace(
                go.Scatter(
                    x=df["Date"],
                    y=df["Rolling_Avg"],
                    mode="lines",
                    name=f"{window}-Day Avg",
                    line=dict(color="#00d4ff", width=4),
                )
            )
            fig_trend.update_layout(
                template="plotly_dark", height=400, margin=dict(l=10, r=10, t=10, b=10)
            )
            st.plotly_chart(fig_trend, use_container_width=True)

            # Weekly Chart
            fig_weekly = px.bar(
                weekly_df,
                x="Date",
                y="Weight",
                color_discrete_sequence=["#ff4b4b"],
                text_auto=".1f",
            )
            fig_weekly.update_layout(
                template="plotly_dark", height=300, margin=dict(l=10, r=10, t=10, b=10)
            )
            st.plotly_chart(fig_weekly, use_container_width=True)

        # --- TAB 2: EDIT DATA ---
        with tab2:
            st.subheader("Manage Data")

            # Since Streamlit's "Add Row" button is fixed at the bottom,
            # we use session_state to allow manual prepending if desired.
            if "data_to_edit" not in st.session_state:
                st.session_state.data_to_edit = display_df[["Date", "Weight"]].copy()

            col1, col2 = st.columns([1, 5])
            if col1.button("➕ Add Row"):
                # Get the most recent weight if data exists, otherwise default to 0.0
                if not st.session_state.data_to_edit.empty:
                    # iloc[0] is used because the table is sorted newest-to-oldest
                    last_weight = float(st.session_state.data_to_edit.iloc[0]["Weight"])
                else:
                    last_weight = 0.0

                new_empty = pd.DataFrame(
                    [{"Date": datetime.today(), "Weight": last_weight}]
                )

                st.session_state.data_to_edit = pd.concat(
                    [new_empty, st.session_state.data_to_edit], ignore_index=True
                )
                st.rerun()

            updated_df = st.data_editor(
                st.session_state.data_to_edit,
                column_config={
                    "Date": st.column_config.DateColumn("Date", required=True),
                    "Weight": st.column_config.NumberColumn(
                        "Weight (kg)", format="%.1f"
                    ),
                },
                num_rows="dynamic",
                hide_index=True,
                key="bulk_editor",
            )

            if st.button("Save Changes", type="primary"):
                try:
                    updated_df = updated_df.dropna(subset=["Date"])
                    updated_df["Date"] = pd.to_datetime(updated_df["Date"])
                    # Force Descending Sort for GSheets storage
                    updated_df = updated_df.sort_values(by="Date", ascending=False)
                    updated_df["Date"] = updated_df["Date"].dt.strftime("%Y-%m-%d")

                    conn.update(worksheet="Sheet1", data=updated_df)
                    st.success("Database synchronized!")
                    del (
                        st.session_state.data_to_edit
                    )  # Clear local state to fetch fresh from DB
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {e}")

    else:
        st.info("Please log your first entry to generate charts.")
