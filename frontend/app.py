from pathlib import Path
import sys
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend import tools
from backend.llm_compiler import compile_user_intent
from backend.state_manager import execute_rule, get_device_states
st.set_page_config(page_title='Smart_Things_Assistant', page_icon='⚡', layout='wide', initial_sidebar_state='collapsed')
css_path = Path(__file__).with_name('style.css')
st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
API_BASE = st.sidebar.text_input('FastAPI endpoint', 'http://127.0.0.1:8000').rstrip('/')

def api_get_or_local(path: str, fallback):
    try:
        response = requests.get(f'{API_BASE}{path}', timeout=1.5)
        if response.ok:
            return response.json()
    except requests.RequestException:
        pass
    return fallback()

def api_post_or_local(path: str, payload: dict, fallback):
    try:
        response = requests.post(f'{API_BASE}{path}', json=payload, timeout=4)
        if response.ok:
            return response.json()
    except requests.RequestException:
        pass
    return fallback()

def local_telemetry():
    df = tools.load_telemetry()
    latest = df.timestamp.max()
    recent = df[df.timestamp >= latest - pd.Timedelta(hours=24)]
    return {'time_series': recent.to_dict(orient='records'), 'phantom_loads': tools.detect_phantom_loads(), 'anomalies': tools.predict_appliance_anomalies(), 'solar_weather': tools.get_solar_and_weather_recommendations(), 'virtual_device_states': get_device_states()}

def compile_intent(prompt: str):
    return api_post_or_local('/chat-compile', {'user_prompt': prompt}, lambda: compile_user_intent(prompt))

def simulate(alpha: float, ac_temp_c: float, ai_mode: bool):
    return api_post_or_local('/simulate', {'alpha': alpha, 'ac_temp_c': ac_temp_c, 'enable_ai_mode': ai_mode}, lambda: tools.simulate_comfort_vs_cost(alpha, ac_temp_c, ai_mode))

def execute(rule: dict, confirmed: bool):
    result = api_post_or_local('/execute-rule', {'rule': rule, 'hitl_confirmed': confirmed}, lambda: execute_rule({**rule, 'hitl_confirmed': confirmed}))
    return result
st.markdown('<div class="hero"><div class="muted">SAMSUNG INNOVATION CHALLENGE · PROVIDED SIC IOT DATASET</div>\n<h1 style="margin:5px 0 2px">Smart_Things_Assistant</h1>\n<div class="muted">Hourly home energy, observed TOU prices, HVAC comfort, and CSV-grounded routine compilation.</div></div>', unsafe_allow_html=True)
try:
    df = tools.load_telemetry()
    telemetry = api_get_or_local('/telemetry', local_telemetry)
except Exception as exc:
    st.error(f'Could not load the provided dataset: {exc}')
    st.stop()
left, center, right = st.columns([1.05, 1.25, 1.05], gap='medium')
with left:
    st.subheader('Home & appliances')
    st.caption(f'{df.home_id.iloc[0]} · {len(df):,} hourly rows · {df.timestamp.min():%b %d}–{df.timestamp.max():%b %d, %Y}')
    states = telemetry.get('virtual_device_states', get_device_states())
    device_display = [('HVAC', 'hvac', 'hvac_usage_kwh'), ('Robot vacuum', 'robot_vacuum', 'robot_vacuum_usage_kwh'), ('Washer / dryer', 'washer_dryer', 'washer_dryer_usage_kwh'), ('Dishwasher', 'dishwasher', 'dishwasher_usage_kwh')]
    for label, device_id, column in device_display:
        total = float(df[column].sum())
        st.markdown(f'<div class="device-card"><div class="device-title">{label}</div><div class="muted">CSV channel · {column}</div><div style="margin-top:9px"><span class="watt">{total:,.1f} kWh</span><span class="muted"> observed</span></div></div>', unsafe_allow_html=True)
        if device_id == 'hvac':
            current_mode = states[device_id]['eco_mode']
            eco_mode = st.toggle('Simulated HVAC eco mode', value=current_mode, key='csv_hvac_eco')
            if eco_mode != current_mode:
                outcome = execute({'rule_name': 'HVAC Eco Mode Toggle', 'risk_tier': 'TIER_0_SAFE', 'smartthings_rule': {'actions': [{'then': [{'device_id': 'hvac', 'command': 'ecoMode', 'value': eco_mode}]}]}}, False)
                st.toast('Virtual HVAC eco mode updated.' if outcome.get('execution_allowed') else outcome.get('validation_message', 'Update blocked.'))
    st.markdown("<div class='glass-card'><b>Comfort vs. cost</b><div class='muted'>Uses the observed HVAC share and supplied USD time-of-use costs.</div></div>", unsafe_allow_html=True)
    alpha = st.slider('Comfort preference α · 0 = savings, 1 = comfort', 0.0, 1.0, 0.4, 0.05)
    cool_set = st.slider('Cooling setpoint', 18, 30, 25, 1, format='%d °C')
    ai_mode = st.toggle('Simulate HVAC eco savings', value=True)
    sim = simulate(alpha, cool_set, ai_mode)
    col_a, col_b = st.columns(2)
    col_a.metric('Projected 30-day bill', f"${sim['projected_bill_usd']:,.2f}")
    col_b.metric('Estimated savings', f"${sim['estimated_savings_usd']:,.2f}")
    st.caption(f"Projected use {sim['projected_30_day_kwh']:,.1f} kWh · Utility {sim['utility_score']:.2f} · dataset mean rate ${sim['observed_average_rate_usd_per_kwh']:.3f}/kWh")
with center:
    st.subheader('Energy & tariff insights')
    series = pd.DataFrame(telemetry.get('time_series', []))
    if series.empty:
        series = df[df.timestamp >= df.timestamp.max() - pd.Timedelta(hours=24)].copy()
    series['timestamp'] = pd.to_datetime(series['timestamp'])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.timestamp, y=series.total_usage_kwh, name='Whole home', line={'color': '#00A9E0', 'width': 2.6}, fill='tozeroy', fillcolor='rgba(0,169,224,.10)'))
    for label, column, color in [('HVAC', 'hvac_usage_kwh', '#00E676'), ('Washer/dryer', 'washer_dryer_usage_kwh', '#FFC857'), ('Dishwasher', 'dishwasher_usage_kwh', '#A78BFA')]:
        fig.add_trace(go.Scatter(x=series.timestamp, y=series[column], name=label, line={'color': color, 'width': 1.5}))
    fig.update_layout(template='plotly_dark', height=270, margin={'l': 8, 'r': 8, 't': 24, 'b': 8}, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(12,18,32,.45)', legend={'orientation': 'h', 'y': 1.15}, yaxis_title='Hourly kWh', hovermode='x unified')
    st.plotly_chart(fig, width='stretch', alt='Whole-home and appliance hourly energy use')
    rec = telemetry.get('solar_weather', tools.get_solar_and_weather_recommendations())
    st.info(f"Observed tariffs: Peak ${rec['peak_rate_usd_per_kwh']:.3f}/kWh · Off-Peak ${rec['off_peak_rate_usd_per_kwh']:.3f}/kWh · estimated rate reduction {rec['estimated_rate_reduction_pct']:.1f}%.")
    st.caption(rec['schedule_recommendation'])
    st.warning(rec['hvac_recommendation'])
    st.markdown('#### Advanced anomaly predictor')
    anomalies = telemetry.get('anomalies', [])
    if not anomalies:
        st.success('No sustained anomalies found. One-off appliance cycles and weather-driven HVAC changes are not flagged.')
    for anomaly in anomalies:
        message = f"**{anomaly.get('diagnosis')}**  \n{anomaly.get('timestamp', '')} · {anomaly.get('remediation')}"
        if anomaly.get('severity') == 'high':
            st.error(message)
        else:
            st.warning(message)
    st.markdown('#### Overnight baseline radar')
    baseline = telemetry.get('phantom_loads', [])
    if baseline:
        item = baseline[0]
        st.metric('01:00–05:00 whole-home baseline', f"{item['equivalent_average_watts']:.0f} W", f"${item['annualized_cost_usd']:.2f}/yr annualized")
        st.caption(item['data_limit'])
with right:
    st.subheader('Routine compiler')
    st.caption('Compiles only device categories represented by the supplied CSV.')
    quick = {'Schedule laundry off-peak': 'Schedule the washer and dryer for the Off-Peak tariff period', 'Sync dishwasher with off-peak': 'Schedule dishwasher use during Off-Peak hours', 'Tune HVAC for warm peak hours': 'Enable HVAC eco mode and raise cooling setpoint by one degree', 'Check nightly phantom loads': 'Check nightly phantom loads'}
    for label, text in quick.items():
        if st.button(label, width='stretch', key=f'quick_{label}'):
            st.session_state['csv_intent'] = text
    prompt = st.text_area('Describe a routine', key='csv_intent', height=105, placeholder='For example: schedule the robot vacuum for Off-Peak')
    if st.button('Compile routine', type='primary', width='stretch'):
        if not prompt.strip():
            st.warning('Describe a routine first.')
        else:
            try:
                st.session_state['csv_compiled'] = compile_intent(prompt)
            except Exception as exc:
                st.error(f'Compilation failed: {exc}')
    compiled = st.session_state.get('csv_compiled')
    if compiled:
        sensitive = compiled.get('requires_hitl_override', False)
        if compiled.get('risk_tier') == 'TIER_2_PROTECTED_CRITICAL':
            st.markdown(f"<div class='tier2'><b>PROTECTED ACTION · HITL REQUIRED</b><br>{compiled.get('explanation', '')}</div>", unsafe_allow_html=True)
        elif sensitive:
            st.warning(f"{compiled.get('risk_tier')} · confirmation required")
        else:
            st.success(f"{compiled.get('rule_name')} · {compiled.get('risk_tier')}")
        st.metric('Estimated monthly savings', f"${compiled.get('estimated_monthly_savings_usd', 0):,.2f}")
        st.caption(compiled.get('explanation', ''))
        if compiled.get('unsupported_devices'):
            st.info('Unavailable in this CSV: ' + ', '.join(compiled['unsupported_devices']))
        with st.expander('View raw SmartThings Rules API JSON'):
            st.json(compiled.get('smartthings_rule', {}), expanded=True)
        confirmed = st.checkbox('I confirm this comfort-sensitive routine', key='csv_hitl') if sensitive else False
        if not compiled.get('executable', True):
            st.info('No executable routine was created because the requested device is not represented in this CSV.')
        elif st.button('Confirm & apply routine' if sensitive else 'Approve & apply routine', type='primary', width='stretch', disabled=sensitive and (not confirmed)):
            outcome = execute(compiled, confirmed)
            if outcome.get('execution_allowed'):
                st.success('Routine applied to virtual device state.')
            else:
                st.error(outcome.get('validation_message', 'Execution blocked.'))
