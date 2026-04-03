import streamlit as st
import streamlit_authenticator as stauth
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Bulking Dashboard", layout="wide")

# --- AUTHENTICATION SETUP ---
credentials = dict(st.secrets["credentials"])
cookie = st.secrets["cookie"]
authenticator = stauth.Authenticate(credentials, cookie["name"], cookie["key"], cookie["expiry_days"])
authenticator.login()

if st.session_state["authentication_status"]:
    authenticator.logout("Logout", "sidebar")
    
    # 1. Initialize Connection & Fetch Data
    conn = st.connection("gsheets", type=GSheetsConnection)

    @st.cache_data(ttl=600)
    def fetch_data():
        data = conn.read(worksheet="Sheet1")
        data['Date'] = pd.to_datetime(data['Date'])
        return data.sort_values(by="Date")

    df = fetch_data()

    # --- SIDEBAR CONTROLS ---
    with st.sidebar:
        st.header("Settings")
        window = st.slider("Rolling Average Window (Days)", 1, 30, 7)
        
        st.divider()
        st.header("Log New Entry")
        with st.form("weight_form", clear_on_submit=True):
            entry_date = st.date_input("Date", value=datetime.today())
            entry_weight = st.number_input("Weight (kg)", min_value=30.0, max_value=200.0, step=0.1)
            submit_button = st.form_submit_button("Submit Entry")

        if submit_button:
            new_row = pd.DataFrame([{"Date": entry_date.strftime("%Y-%m-%d"), "Weight": entry_weight}])
            updated_df = pd.concat([df, new_row], ignore_index=True)
            conn.update(worksheet="Sheet1", data=updated_df)
            st.cache_data.clear()
            st.rerun()

    # --- DATA PROCESSING & DASHBOARD ---
    if not df.empty:
        # Calculations
        df['Rolling_Avg'] = df['Weight'].rolling(window=window).mean()
        weekly_df = df.resample('W-SUN', on='Date').mean(numeric_only=True).reset_index()

        # Metrics Row
        st.title("🦭 Bulking Dashboard")
        m1, m2, m3 = st.columns(3)
        latest_weight = df.iloc[-1]['Weight']
        latest_rolling = df.iloc[-1]['Rolling_Avg']
        total_gained = latest_weight - df.iloc[0]['Weight']

        m1.metric("Current", f"{latest_weight:.1f} kg")
        m2.metric(f"{window}-Day Avg", f"{latest_rolling:.2f} kg" if pd.notna(latest_rolling) else "N/A")
        m3.metric("Total Progress", f"{total_gained:+.1f} kg")

        # --- CHART 1: DAILY VS ROLLING ---
        st.subheader("Weight Trend")
        fig_trend = go.Figure()

        # Daily Weight (Faint dots)
        fig_trend.add_trace(go.Scatter(
            x=df['Date'], y=df['Weight'],
            mode='markers',
            name='Daily Weight',
            marker=dict(color='rgba(255, 255, 255, 0.2)', size=6),
            hovertemplate="Date: %{x}<br>Weight: %{y}kg<extra></extra>"
        ))

        # Rolling Average (Thick Line)
        fig_trend.add_trace(go.Scatter(
            x=df['Date'], y=df['Rolling_Avg'],
            mode='lines',
            name=f'{window}-Day Avg',
            line=dict(color='#00d4ff', width=4),
            hovertemplate="Date: %{x}<br>Avg: %{y:.2f}kg<extra></extra>"
        ))

        fig_trend.update_layout(
            template="plotly_dark",
            height=400,
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=False, title="Weight (kg)")
        )
        st.plotly_chart(fig_trend, use_container_width=True)

        # --- CHART 2: WEEKLY BLOCKS ---
        st.subheader("Weekly Block Averages")
        fig_weekly = px.bar(
            weekly_df, x='Date', y='Weight',
            color_discrete_sequence=['#ff4b4b'],
            text_auto='.1f'
        )
        
        fig_weekly.update_layout(
            template="plotly_dark",
            height=300,
            xaxis_title=None,
            yaxis_title="Avg Weight",
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=False),
            margin=dict(l=10, r=10, t=10, b=10)
        )
        st.plotly_chart(fig_weekly, use_container_width=True)

        # --- CALORIE ADVICE ---
        if len(df) >= 14:
            diff = df.iloc[-7:]['Weight'].mean() - df.iloc[-14:-7]['Weight'].mean()
            st.divider()
            if diff > 0.2:
                st.warning(f"⚠️ **Eat less.** Weekly gain: {diff:.2f}kg. Slow down to minimize fat gain.")
            elif diff < 0.1:
                st.success(f"🍴 **Eat more!** Weekly gain: {diff:.2f}kg. Increase calories for better growth.")
            else:
                st.info(f"✅ **Perfect.** Weekly gain: {diff:.2f}kg. Maintain current calories.")

    else:
        st.info("Please log your first entry to generate charts.")

elif st.session_state["authentication_status"] is False:
    st.error("Invalid credentials.")