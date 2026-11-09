from pathlib import Path
import sys
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from backend import tools
from backend.llm_compiler import compile_user_intent
from backend.state_manager import execute_rule, get_device_states
app = FastAPI(title='Smart_Things_Assistant', version='2.0.0')

class SimulationRequest(BaseModel):
    alpha: float = Field(0.5, ge=0, le=1)
    ac_temp_c: float = Field(24, ge=16, le=32)
    enable_ai_mode: bool = True

class CompileRequest(BaseModel):
    user_prompt: str = Field(min_length=1)

class ExecuteRequest(BaseModel):
    rule: dict[str, Any]
    hitl_confirmed: bool = False

@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok', 'service': app.title}

@app.get('/telemetry')
def telemetry() -> dict[str, Any]:
    try:
        df = tools.load_telemetry()
        cutoff = df.timestamp.max() - __import__('pandas').Timedelta(hours=24)
        recent = df[df.timestamp >= cutoff]
        appliance_totals = {label: round(float(df[column].sum()), 2) for label, column in tools.APPLIANCE_COLUMNS.items()}
        recent_columns = ['timestamp', 'total_usage_kwh', 'hvac_usage_kwh', 'robot_vacuum_usage_kwh', 'washer_dryer_usage_kwh', 'dishwasher_usage_kwh', 'cost_usd', 'price_tou_usd_per_kwh', 'tariff_period', 'outdoor_temp_c', 'indoor_temp_c', 'occupied']
        return {'summary': {'home_id': str(df.home_id.iloc[0]), 'records': int(len(df)), 'start_timestamp': df.timestamp.min().isoformat(), 'end_timestamp': df.timestamp.max().isoformat(), 'observed_kwh': round(float(df.total_usage_kwh.sum()), 2), 'observed_cost_usd': round(float(df.cost_usd.sum()), 2), 'observed_days': round(tools._elapsed_days(df), 2), 'appliance_energy_kwh': appliance_totals}, 'time_series': recent[recent_columns].assign(timestamp=lambda x: x.timestamp.astype(str)).to_dict(orient='records'), 'devices': [{'device_id': key, 'device_name': name, 'source_column': column, 'total_kwh': round(float(df[column].sum()), 2), 'average_hourly_kwh': round(float(df[column].mean()), 4)} for (key, name), column in zip([('hvac', 'HVAC'), ('robot_vacuum', 'Robot vacuum'), ('washer_dryer', 'Washer/dryer'), ('dishwasher', 'Dishwasher')], tools.APPLIANCE_COLUMNS.values())], 'phantom_loads': tools.detect_phantom_loads(), 'anomalies': tools.predict_appliance_anomalies(), 'solar_weather': tools.get_solar_and_weather_recommendations(), 'virtual_device_states': get_device_states()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'CSV telemetry could not be loaded: {exc}') from exc

@app.post('/simulate')
def simulate(request: SimulationRequest) -> dict[str, Any]:
    return tools.simulate_comfort_vs_cost(request.alpha, request.ac_temp_c, request.enable_ai_mode)

@app.post('/chat-compile')
def chat_compile(request: CompileRequest) -> dict[str, Any]:
    try:
        return compile_user_intent(request.user_prompt)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Routine compilation failed: {exc}') from exc

@app.post('/execute-rule')
def run_rule(request: ExecuteRequest) -> dict[str, Any]:
    rule = dict(request.rule)
    rule['hitl_confirmed'] = request.hitl_confirmed
    result = execute_rule(rule)
    if not result.get('execution_allowed'):
        raise HTTPException(status_code=403, detail=result)
    return result
