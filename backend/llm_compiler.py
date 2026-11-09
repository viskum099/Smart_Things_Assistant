import os
import re
from typing import Any
from pydantic import BaseModel, Field
from backend import tools
from backend.state_manager import intercept_and_validate_rule

class CompiledRoutine(BaseModel):
    rule_name: str
    risk_tier: str
    requires_hitl_override: bool
    estimated_monthly_savings_usd: float = Field(ge=0)
    smartthings_rule: dict[str, Any]
    explanation: str
    unsupported_devices: list[str] = []

def _payload(name: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {'name': name, 'timeZoneId': 'Asia/Kolkata', 'executionLocation': 'Cloud', 'actions': [{'if': [{'equals': {'left': {'type': 'device', 'id': 'home'}, 'right': {'type': 'boolean', 'value': True}}}], 'and': [], 'between': {'start': '00:00', 'end': '23:59'}, 'equals': True, 'then': actions}]}

def _normalize_payload(payload: dict[str, Any], name: str) -> dict[str, Any]:
    normalized = []
    for action in payload.get('actions', []):
        if not isinstance(action, dict):
            continue
        leaves = action.get('then', []) if isinstance(action.get('then'), list) else [action]
        leaves = [leaf for leaf in leaves if isinstance(leaf, dict) and leaf.get('command')]
        if leaves:
            normalized.append({'if': action.get('if', [{'equals': {'left': {'type': 'device', 'id': 'home'}, 'right': {'type': 'boolean', 'value': True}}}]), 'and': action.get('and', []), 'between': action.get('between', {'start': '00:00', 'end': '23:59'}), 'equals': action.get('equals', True), 'then': leaves})
    return {'name': payload.get('name', name), 'timeZoneId': 'Asia/Kolkata', 'executionLocation': 'Cloud', 'actions': normalized}

def _guard_dataset_actions(compiled: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_payload(compiled.get('smartthings_rule', {}), compiled['rule_name'])
    allowed = {'hvac', 'robot_vacuum', 'washer_dryer', 'dishwasher'}
    unsupported = set(compiled.get('unsupported_devices', []))
    kept = []
    for wrapper in payload['actions']:
        valid_leaves = []
        for action in wrapper['then']:
            device = action.get('device_id')
            if device in allowed:
                valid_leaves.append(action)
            elif device:
                unsupported.add(str(device))
        if valid_leaves:
            kept.append({**wrapper, 'then': valid_leaves})
    payload['actions'] = kept
    compiled['smartthings_rule'] = payload
    compiled['unsupported_devices'] = sorted(unsupported)
    compiled['executable'] = bool(kept)
    if unsupported:
        compiled['explanation'] = (compiled.get('explanation', '') + ' Unsupported device actions were removed because the supplied CSV has no measurements for them.').strip()
    return compiled

def deterministic_compile(user_prompt: str) -> dict[str, Any]:
    prompt = user_prompt.lower()
    actions: list[dict[str, Any]] = []
    unsupported: list[str] = []
    name = 'SIC Energy Saving Routine'
    explanation = 'Compiled conservatively from the supplied hourly energy and tariff data.'
    savings = 0.0
    risk = 'TIER_0_SAFE'
    if any((token in prompt for token in ('fridge', 'refrigerator'))):
        unsupported.append('refrigerator')
        explanation = 'The supplied CSV has no refrigerator channel. No refrigerator command was generated; available appliances remain unchanged.'
        name = 'Unsupported Refrigerator Request'
    elif any((token in prompt for token in ('solar', 'solar peak'))):
        explanation = 'Solar generation is not included in this CSV. I can schedule available appliances in observed Off-Peak tariff periods instead.'
        actions = [{'device_id': device, 'command': 'schedule', 'period': 'Off-Peak'} for device in ('washer_dryer', 'dishwasher')]
        name = 'Off-Peak Appliance Schedule'
        savings = _estimated_shift_savings(['washer_dryer_usage_kwh', 'dishwasher_usage_kwh'])
    elif any((token in prompt for token in ('washer', 'laundry', 'dishwasher', 'vacuum', 'appliance', 'off-peak', 'off peak'))):
        selected = []
        if any((token in prompt for token in ('washer', 'laundry', 'washer/dryer'))):
            selected.append('washer_dryer')
        if 'dishwasher' in prompt or ('kitchen' in prompt and 'appliance' in prompt):
            selected.append('dishwasher')
        if any((token in prompt for token in ('vacuum', 'robot'))):
            selected.append('robot_vacuum')
        if not selected:
            selected = ['washer_dryer', 'dishwasher']
        actions = [{'device_id': device, 'command': 'schedule', 'period': 'Off-Peak'} for device in selected]
        columns = [tools.APPLIANCE_COLUMNS['Washer/dryer'] if d == 'washer_dryer' else tools.APPLIANCE_COLUMNS['Dishwasher'] if d == 'dishwasher' else tools.APPLIANCE_COLUMNS['Robot vacuum'] for d in selected]
        savings = _estimated_shift_savings(columns)
        name = 'Observed Off-Peak Appliance Schedule'
        explanation = 'Schedule the selected dataset appliance categories in the observed Off-Peak period; no solar signal is assumed.'
    elif any((token in prompt for token in ('hvac', 'air conditioner', 'air conditioning', 'cooling', 'heatwave', 'heating', 'thermostat', 'setpoint', 'temperature'))):
        match = re.search('(?:to|at|setpoint(?:\\s+to)?)\\s*(-?\\d+(?:\\.\\d+)?)', prompt)
        if 'heat' in prompt and (not any((word in prompt for word in ('heatwave', 'hot', 'cool')))):
            command, device_id, current = ('setHeatingSetpoint', 'hvac', 21.0)
            target = float(match.group(1)) if match else current
        else:
            command, device_id = ('setCoolingSetpoint', 'hvac')
            df = tools.load_telemetry()
            current = float(df.loc[df.hvac_mode.eq('cool'), 'cool_set_c'].median()) if df.hvac_mode.eq('cool').any() else 24.0
            target = float(match.group(1)) if match else current + 1
        if abs(target - current) > 2:
            risk = 'TIER_1_COMFORT_SENSITIVE'
        actions = [{'device_id': 'hvac', 'command': 'ecoMode', 'value': True}, {'device_id': device_id, 'command': command, 'value': target}]
        savings = round(max(0, tools.simulate_comfort_vs_cost(0.0, target, True)['estimated_savings_usd']), 2)
        name = 'HVAC Comfort and Energy Routine'
        explanation = f'Enable simulated HVAC eco mode and set {target:g}°C. A setpoint shift over 2°C requires confirmation.' if risk.endswith('1_COMFORT_SENSITIVE') else f'Enable simulated HVAC eco mode and make a modest setpoint adjustment from the observed {current:g}°C baseline.'
    elif any((token in prompt for token in ('phantom', 'standby', 'night'))):
        explanation = 'This dataset has no plug-level or standby device measurements, so specific phantom loads cannot be identified or switched off. The dashboard shows an aggregate overnight baseline estimate.'
        name = 'Overnight Baseline Review'
    else:
        actions = [{'device_id': 'hvac', 'command': 'ecoMode', 'value': True}]
        savings = round(tools.simulate_comfort_vs_cost(0.25, 25, True)['estimated_savings_usd'], 2)
        name = 'HVAC Eco Mode'
        explanation = 'Enable simulated HVAC eco mode; its savings estimate is based on observed HVAC energy share and time-of-use costs.'
    rule = {'rule_name': name, 'risk_tier': risk, 'requires_hitl_override': risk != 'TIER_0_SAFE', 'estimated_monthly_savings_usd': max(0, savings), 'explanation': explanation, 'unsupported_devices': unsupported, 'executable': bool(actions), 'smartthings_rule': _payload(name, actions)}
    return intercept_and_validate_rule(rule)

def _estimated_shift_savings(columns: list[str]) -> float:
    df = tools.load_telemetry()
    peak = df.tariff_period.astype(str).str.lower().eq('peak')
    off = df.tariff_period.astype(str).str.lower().eq('off-peak')
    price_diff = float(df.loc[peak, 'price_tou_usd_per_kwh'].mean() - df.loc[off, 'price_tou_usd_per_kwh'].mean()) if peak.any() and off.any() else 0.0
    elapsed_days = max((df.timestamp.max() - df.timestamp.min()).total_seconds() / 86400 + 1 / 24, 1 / 24)
    energy = float(df[columns].sum().sum()) / elapsed_days * 30
    return round(max(0, price_diff * energy), 2)

def _gemini_compile(user_prompt: str) -> dict[str, Any]:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    funcs = [types.FunctionDeclaration(name='simulate_comfort_vs_cost', description='Project HVAC energy cost using the supplied CSV, in USD.', parameters={'type': 'OBJECT', 'properties': {'alpha': {'type': 'NUMBER'}, 'ac_temp_c': {'type': 'NUMBER'}, 'enable_ai_mode': {'type': 'BOOLEAN'}}, 'required': ['alpha', 'ac_temp_c', 'enable_ai_mode']}), types.FunctionDeclaration(name='detect_phantom_loads', description='Estimate aggregate overnight baseline; the CSV has no plug attribution.'), types.FunctionDeclaration(name='get_solar_and_weather_recommendations', description='Read outdoor weather and observed peak/off-peak price recommendations.'), types.FunctionDeclaration(name='predict_appliance_anomalies', description='Find rolling 24-hour anomalies across CSV energy columns.'), types.FunctionDeclaration(name='lookup_hardware_manual', description='Check whether a dataset appliance channel or hardware data exists.', parameters={'type': 'OBJECT', 'properties': {'device_id': {'type': 'STRING'}}, 'required': ['device_id']})]
    tool = types.Tool(function_declarations=funcs)
    dispatcher = {'simulate_comfort_vs_cost': tools.simulate_comfort_vs_cost, 'detect_phantom_loads': tools.detect_phantom_loads, 'get_solar_and_weather_recommendations': tools.get_solar_and_weather_recommendations, 'predict_appliance_anomalies': tools.predict_appliance_anomalies, 'lookup_hardware_manual': tools.lookup_hardware_manual}
    response = client.models.generate_content(model='gemini-2.5-flash', contents=user_prompt, config=types.GenerateContentConfig(tools=[tool], response_mime_type='application/json', response_schema=CompiledRoutine, system_instruction='Compile only routines for hvac, robot_vacuum, washer_dryer, or dishwasher, which are present in the supplied CSV. Do not invent refrigerator, plug, or solar measurements. Use USD. Protected actions need HITL.'))
    calls = [part.function_call for candidate in response.candidates or [] for part in candidate.content.parts if getattr(part, 'function_call', None)]
    if calls:
        results = [types.Part.from_function_response(name=call.name, response={'result': dispatcher[call.name](**dict(call.args or {}))}) for call in calls if call.name in dispatcher]
        response = client.models.generate_content(model='gemini-2.5-flash', contents=[user_prompt, response.candidates[0].content, *results], config=types.GenerateContentConfig(tools=[tool], response_mime_type='application/json', response_schema=CompiledRoutine))
    compiled = CompiledRoutine.model_validate_json(response.text or '').model_dump()
    compiled = _guard_dataset_actions(compiled)
    return intercept_and_validate_rule(compiled)

def compile_user_intent(user_prompt: str) -> dict[str, Any]:
    if not user_prompt or not user_prompt.strip():
        raise ValueError('Please describe the routine you want to create.')
    if not os.getenv('GEMINI_API_KEY'):
        return deterministic_compile(user_prompt)
    try:
        return _gemini_compile(user_prompt)
    except Exception as exc:
        result = deterministic_compile(user_prompt)
        result['compiler_mode'] = 'deterministic_fallback'
        result['compiler_note'] = f'Gemini was unavailable ({type(exc).__name__}); compiled locally instead.'
        return result
