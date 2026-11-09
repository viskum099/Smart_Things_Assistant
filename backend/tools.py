from pathlib import Path
import sys
from typing import Any
import numpy as np
import pandas as pd
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / 'data' / 'sic_iot_dataset.csv'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from data.in_memory_kb import DATASET_FIELD_KB, SIC_DATASET_SCHEMA
REQUIRED_COLUMNS = list(SIC_DATASET_SCHEMA)
APPLIANCE_COLUMNS = {'HVAC': 'hvac_usage_kwh', 'Robot vacuum': 'robot_vacuum_usage_kwh', 'Washer/dryer': 'washer_dryer_usage_kwh', 'Dishwasher': 'dishwasher_usage_kwh'}

def load_telemetry() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f'Expected the supplied dataset at {DATA_PATH}.')
    df = pd.read_csv(DATA_PATH, parse_dates=['timestamp'])
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f'SIC dataset is missing required columns: {sorted(missing)}')
    numeric = [column for column in REQUIRED_COLUMNS if column not in {'home_id', 'timestamp', 'hvac_mode', 'tariff_period'}]
    for column in numeric:
        df[column] = pd.to_numeric(df[column], errors='coerce').fillna(0)
    df['occupied'] = df['occupied'].astype(bool)
    return df.sort_values('timestamp').reset_index(drop=True)

def _elapsed_days(df: pd.DataFrame) -> float:
    return max((df.timestamp.max() - df.timestamp.min()).total_seconds() / 86400 + 1 / 24, 1 / 24)

def _average_unit_cost(df: pd.DataFrame) -> float:
    energy = float(df.total_usage_kwh.sum())
    return float(df.cost_usd.sum() / energy) if energy > 0 else float(df.price_tou_usd_per_kwh.mean())

def simulate_comfort_vs_cost(alpha: float, ac_temp_c: float, enable_ai_mode: bool) -> dict[str, Any]:
    alpha = float(np.clip(alpha, 0, 1))
    ac_temp_c = float(np.clip(ac_temp_c, 16, 32))
    df = load_telemetry()
    current_kwh = float(df.total_usage_kwh.sum())
    days = _elapsed_days(df)
    average_daily = current_kwh / days
    projected_kwh = average_daily * 30
    projected_cost = float(df.cost_usd.sum() / days * 30)
    hvac_kwh = float(df.hvac_usage_kwh.sum())
    hvac_share = hvac_kwh / current_kwh if current_kwh > 0 else 0.0
    representative_cool_setpoint = float(df.loc[df.hvac_mode.eq('cool'), 'cool_set_c'].median()) if df.hvac_mode.eq('cool').any() else 24.0
    setpoint_delta = ac_temp_c - representative_cool_setpoint
    hvac_factor = max(0.45, 1 - 0.06 * setpoint_delta)
    if enable_ai_mode:
        hvac_factor *= 0.9
    adjusted_kwh = projected_kwh * (1 - hvac_share) + projected_kwh * hvac_share * hvac_factor
    adjusted_cost = projected_cost * (adjusted_kwh / projected_kwh) if projected_kwh else 0.0
    savings = max(0.0, projected_cost - adjusted_cost)
    discomfort = abs(setpoint_delta) * 2.5 + max(0, abs(setpoint_delta) - 2) ** 2 * 4
    utility = (1 - alpha) * savings - alpha * discomfort
    return {'alpha': alpha, 'ac_temp_c': ac_temp_c, 'reference_cool_setpoint_c': round(representative_cool_setpoint, 1), 'enable_ai_mode': bool(enable_ai_mode), 'source_currency': 'USD', 'current_kwh': round(current_kwh, 2), 'elapsed_days': round(days, 2), 'projected_30_day_kwh': round(adjusted_kwh, 2), 'projected_bill_usd': round(adjusted_cost, 2), 'baseline_bill_usd': round(projected_cost, 2), 'estimated_savings_usd': round(savings, 2), 'discomfort_penalty': round(discomfort, 2), 'utility_score': round(utility, 2), 'observed_average_rate_usd_per_kwh': round(_average_unit_cost(df), 4)}

def detect_phantom_loads() -> list[dict[str, Any]]:
    df = load_telemetry()
    overnight = df[df.timestamp.dt.hour.between(1, 4)]
    if overnight.empty:
        return []
    mean_hourly_kwh = float(overnight.total_usage_kwh.mean())
    annual_kwh = mean_hourly_kwh * 4 * 365
    rate = float(overnight.price_tou_usd_per_kwh.mean())
    return [{'device_id': 'aggregate_home_baseline', 'device_name': 'Whole-home overnight baseline (not plug-attributed)', 'mean_hourly_usage_kwh': round(mean_hourly_kwh, 4), 'equivalent_average_watts': round(mean_hourly_kwh * 1000, 1), 'annualized_overnight_kwh': round(annual_kwh, 2), 'annualized_cost_usd': round(annual_kwh * rate, 2), 'window': '01:00-05:00', 'data_limit': 'The source CSV reports appliance categories and cannot identify standby plugs.'}]

def get_solar_and_weather_recommendations() -> dict[str, Any]:
    df = load_telemetry()
    peak = df[df.tariff_period.astype(str).str.lower().eq('peak')]
    off_peak = df[df.tariff_period.astype(str).str.lower().eq('off-peak')]
    hottest = float(df.outdoor_temp_c.max())
    peak_hot = float(peak.outdoor_temp_c.max()) if not peak.empty else None
    rate_peak = float(peak.price_tou_usd_per_kwh.mean()) if not peak.empty else 0.0
    rate_off_peak = float(off_peak.price_tou_usd_per_kwh.mean()) if not off_peak.empty else rate_peak
    peak_hours = sorted(peak.timestamp.dt.hour.unique().tolist()) if not peak.empty else []
    hour_window = f'{min(peak_hours):02d}:00-{(max(peak_hours) + 1) % 24:02d}:00' if peak_hours else None
    hot_peak = peak_hot is not None and peak_hot >= 30
    flexible = ['washer_dryer', 'dishwasher', 'robot_vacuum']
    savings_pct = max(0.0, (rate_peak - rate_off_peak) / rate_peak * 100) if rate_peak else 0.0
    return {'heatwave_detected': hot_peak, 'max_outdoor_temp_c': round(hottest, 1), 'max_peak_period_temp_c': round(peak_hot, 1) if peak_hot is not None else None, 'peak_tou_window_observed': hour_window, 'peak_rate_usd_per_kwh': round(rate_peak, 4), 'off_peak_rate_usd_per_kwh': round(rate_off_peak, 4), 'estimated_rate_reduction_pct': round(savings_pct, 1), 'shiftable_devices': flexible, 'schedule_recommendation': f'Shift washer/dryer, dishwasher, and robot vacuum operation to rows labeled Off-Peak (observed average rate ${rate_off_peak:.3f}/kWh).', 'hvac_recommendation': 'Review cooling setpoint and occupancy during hot Peak hours; use a modest +1 to +2°C setpoint adjustment.' if hot_peak else 'Use the observed HVAC mode, indoor/outdoor temperature, and occupancy trends to tune comfort schedules.', 'solar_data_available': False}

def predict_appliance_anomalies() -> list[dict[str, Any]]:
    df = load_telemetry()
    findings = []
    appliance_energy = df[list(APPLIANCE_COLUMNS.values())].sum(axis=1)
    metrics = [('unattributed_home_load', (df.total_usage_kwh - appliance_energy).clip(lower=0), 'Unattributed whole-home load', 0.2),
        ('hvac', df.hvac_usage_kwh.astype(float), 'HVAC', 0.5)]
    for device_id, values, label, min_excess_kwh in metrics:
        baseline = values.shift(1).rolling(24, min_periods=12)
        baseline_mean = baseline.mean()
        baseline_std = baseline.std().replace(0, np.nan)
        z_score = (values - baseline_mean) / baseline_std
        hits = (z_score > 2.8) & (values > baseline_mean + max(min_excess_kwh, 0.0))
        if device_id == 'hvac':
            stable_context = df.hvac_mode.eq(df.hvac_mode.shift(1)) & df.occupied.eq(df.occupied.shift(1)) & ((df.outdoor_temp_c - df.outdoor_temp_c.shift(1)).abs() < 3)
            hits &= stable_context
        hit_groups = hits.ne(hits.shift()).cumsum()
        sustained_groups = [(group_id, group.index) for group_id, group in hits.groupby(hit_groups) if bool(group.iloc[0]) and len(group) >= 3]
        if sustained_groups:
            indices = [index for _, group_indices in sustained_groups for index in group_indices]
            index = int(z_score.loc[indices].idxmax())
            row = df.loc[index]
            findings.append({'device_id': device_id, 'type': 'sustained_rolling_24h_anomaly', 'severity': 'medium', 'metric': label,
                'duration_hours': max(len(group_indices) for _, group_indices in sustained_groups),
                'z_score': round(float(z_score.loc[index]), 2), 'usage_kwh': round(float(values.loc[index]), 4),
                'timestamp': row.timestamp.isoformat(), 'diagnosis': f'{label} stayed above its context-aware 24-hour baseline for at least three hours.',
                'remediation': 'Check recent usage, occupancy, HVAC mode, and outdoor-temperature context before changing device settings.'})
    return findings

def lookup_hardware_manual(device_id: str) -> dict[str, Any]:
    if device_id not in DATASET_FIELD_KB:
        return {'device_id': device_id, 'found': False, 'message': 'No matching appliance channel or hardware model exists in the supplied CSV.', 'available_channels': list(DATASET_FIELD_KB)}
    return {'device_id': device_id, 'found': True, 'dataset_channel': DATASET_FIELD_KB[device_id], 'manual_available': False, 'message': 'The CSV provides appliance energy categories, but no Samsung model or hardware manual metadata.'}
