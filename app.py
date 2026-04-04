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

# Using .get() prevents KeyError if the session state hasn't initialized properly
if st.session_state.get("authentication_status"):
    authenticator.logout("Logout", "sidebar")

    # Initialize Connection
    conn = st.connection("gsheets", type=GSheetsConnection)

    @st.cache_data(ttl=600)
    def fetch_data():
        data = conn.read(worksheet="Sheet1")
        data = data.dropna(how="all")
        data["Date"] = pd.to_datetime(data["Date"])
        return data.sort_values(by="Date", ascending=False)

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
                # 1. Fetch fresh data
                raw_data = conn.read(worksheet="Sheet1", ttl=0)
                current_gsheet_df = (
                    raw_data.dropna(how="all")
                    if raw_data is not None
                    else pd.DataFrame(columns=["Date", "Weight"])
                )

                # 2. Create new entry as a DataFrame
                new_row = pd.DataFrame(
                    [
                        {
                            "Date": entry_date.strftime("%Y-%m-%d"),
                            "Weight": float(entry_weight),
                        }
                    ]
                )

                # 3. Combine, handle types, and drop duplicates
                final_df = pd.concat([current_gsheet_df, new_row], ignore_index=True)
                final_df["Date"] = pd.to_datetime(final_df["Date"])
                final_df = final_df.drop_duplicates(subset=["Date"], keep="last")

                # 4. CRITICAL: Sort Newest to Oldest before saving
                final_df = final_df.sort_values(by="Date", ascending=False)

                # 5. Convert date back to string for GSheets storage
                final_df["Date"] = final_df["Date"].dt.strftime("%Y-%m-%d")

                # 6. Save (Safety guard removed so you can delete if needed elsewhere)
                conn.update(worksheet="Sheet1", data=final_df)
                st.success("Weight logged successfully!")
                st.cache_data.clear()
                st.rerun()

            except Exception as e:
                st.error(f"Error: {e}")

    # --- DATA PROCESSING & DASHBOARD ---
    # --- TABS SETUP ---
    tab1, tab2 = st.tabs(["📈 Dashboard", "⚙️ Edit Data"])

    # --- TAB 1: DASHBOARD ---
    with tab1:
        if not df.empty:
            display_df = df[["Date", "Weight"]].copy()
            # Calculations
            display_df["Rolling_Avg"] = (
                display_df["Weight"].rolling(window=window).mean()
            )
            weekly_df = (
                display_df.resample("W-SUN", on="Date")
                .mean(numeric_only=True)
                .reset_index()
            )

            # Metrics Row
            st.title("Weight Dashboard")
            m1, m2, m3 = st.columns(3)

            # index 0 is now the LATEST entry
            latest_weight = display_df.iloc[0]["Weight"]
            latest_rolling = display_df.iloc[0]["Rolling_Avg"]

            # Total progress is Latest (index 0) minus Oldest (last index -1)
            total_gained = latest_weight - display_df.iloc[-1]["Weight"]

            m1.metric("Current", f"{latest_weight:.1f} kg")
            m2.metric(
                f"{window}-Day Avg",
                f"{latest_rolling:.2f} kg" if pd.notna(latest_rolling) else "N/A",
            )
            m3.metric("Total Progress", f"{total_gained:+.1f} kg")

            # --- CHART 1: DAILY VS ROLLING ---
            st.subheader("Weight Trend")
            fig_trend = go.Figure()
            fig_trend.add_trace(
                go.Scatter(
                    x=display_df["Date"],
                    y=display_df["Weight"],
                    mode="markers",
                    name="Daily Weight",
                    marker=dict(color="rgba(255, 255, 255, 0.2)", size=6),
                )
            )
            fig_trend.add_trace(
                go.Scatter(
                    x=display_df["Date"],
                    y=display_df["Rolling_Avg"],
                    mode="lines",
                    name=f"{window}-Day Avg",
                    line=dict(color="#00d4ff", width=4),
                )
            )
            fig_trend.update_layout(
                template="plotly_dark", height=400, margin=dict(l=10, r=10, t=10, b=10)
            )
            st.plotly_chart(fig_trend, use_container_width=True)

            # --- CHART 2: WEEKLY BLOCKS ---
            st.subheader("Weekly Block Averages")
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

            # --- CALORIE ADVICE ---
            if len(display_df) >= 14:
                diff = (
                    display_df.iloc[-7:]["Weight"].mean()
                    - display_df.iloc[-14:-7]["Weight"].mean()
                )
                st.divider()
                if diff > 0.2:
                    st.warning(
                        f"⚠️ **Eat less.** Weekly gain: {diff:.2f}kg. Slow down to minimize fat gain."
                    )
                elif diff < 0.1:
                    st.success(
                        f"🍴 **Eat more!** Weekly gain: {diff:.2f}kg. Increase calories for better growth."
                    )
                else:
                    st.info(
                        f"✅ **Perfect.** Weekly gain: {diff:.2f}kg. Maintain current calories."
                    )
        else:
            st.info("Please log your first entry to generate charts.")

    # --- TAB 2: EDIT DATA ---
    # --- TAB 2: EDIT DATA ---
    with tab2:
        st.subheader("Manage Data")
        st.info(
            "💡 **To Delete:** Select the row (click the box on the far left) and hit 'Delete' on your keyboard."
        )

        # Ensure we are looking at the newest data at the top
        edit_df = df.sort_values(by="Date", ascending=False).copy()

        updated_df = st.data_editor(
            edit_df,
            column_config={
                "Date": st.column_config.DateColumn("Date", required=True),
                "Weight": st.column_config.NumberColumn("Weight (kg)", format="%.1f"),
            },
            num_rows="dynamic",  # Allows adding/deleting rows
            hide_index=True,
            key="bulk_editor",
        )

        if st.button("Save Changes", type="primary"):
            try:
                # 1. Clean and Sort
                updated_df = updated_df.dropna(subset=["Date", "Weight"])
                updated_df["Date"] = pd.to_datetime(updated_df["Date"])
                updated_df = updated_df.sort_values(by="Date", ascending=False)

                # 2. Format for GSheets
                updated_df["Date"] = updated_df["Date"].dt.strftime("%Y-%m-%d")

                # 3. Update
                conn.update(worksheet="Sheet1", data=updated_df)
                st.success("Database synchronized!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Update failed: {e}")
