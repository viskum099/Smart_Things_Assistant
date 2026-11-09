from copy import deepcopy
from typing import Any
_DEVICE_STATES: dict[str, dict[str, Any]] = {'hvac': {'mode': 'cool', 'eco_mode': False, 'cool_set_c': 25, 'heat_set_c': 21, 'source_fields': ['hvac_mode', 'cool_set_c', 'heat_set_c']}, 'robot_vacuum': {'scheduled_period': 'Off-Peak', 'source_field': 'robot_vacuum_usage_kwh'}, 'washer_dryer': {'scheduled_period': 'Off-Peak', 'source_field': 'washer_dryer_usage_kwh'}, 'dishwasher': {'scheduled_period': 'Off-Peak', 'source_field': 'dishwasher_usage_kwh'}}
ACTIVE_RULES: list[dict[str, Any]] = []

def get_device_states() -> dict[str, dict[str, Any]]:
    return deepcopy(_DEVICE_STATES)

def _actions(rule: dict[str, Any]) -> list[dict[str, Any]]:
    payload = rule.get('smartthings_rule', rule.get('payload', rule))
    raw = payload.get('actions', []) if isinstance(payload, dict) else []
    flattened = []
    for action in raw:
        if isinstance(action, dict) and isinstance(action.get('then'), list):
            flattened.extend((leaf for leaf in action['then'] if isinstance(leaf, dict)))
        elif isinstance(action, dict):
            flattened.append(action)
    return flattened

def intercept_and_validate_rule(rule_dict: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(rule_dict)
    actions = _actions(result)
    confirmed = bool(result.get('hitl_confirmed', False))
    protected = any((str(a.get('command', '')).lower() == 'off' and any((word in str(a.get('device_id', '')).lower() for word in ('medical', 'security'))) for a in actions))
    requested_tier = result.get('risk_tier', 'TIER_0_SAFE')
    tier = 'TIER_2_PROTECTED_CRITICAL' if protected else requested_tier
    requires = protected or tier == 'TIER_1_COMFORT_SENSITIVE'
    result.update({'risk_tier': tier, 'requires_hitl_override': requires, 'execution_allowed': not requires or confirmed, 'validation_message': 'Protected action needs explicit HITL confirmation.' if protected and (not confirmed) else 'Comfort-sensitive change needs explicit confirmation.' if requires and (not confirmed) else 'Routine passed safety validation.'})
    return result

def execute_rule(rule_dict: dict[str, Any]) -> dict[str, Any]:
    checked = intercept_and_validate_rule(rule_dict)
    if not checked['execution_allowed']:
        return checked
    for action in _actions(checked):
        device = action.get('device_id')
        command = str(action.get('command', '')).lower()
        if device not in _DEVICE_STATES:
            continue
        state = _DEVICE_STATES[device]
        if device == 'hvac':
            if command == 'setmode':
                state['mode'] = action.get('value', state['mode'])
            elif command == 'setcoolingsetpoint':
                state['cool_set_c'] = action.get('value', state['cool_set_c'])
            elif command == 'setheatingsetpoint':
                state['heat_set_c'] = action.get('value', state['heat_set_c'])
            elif command == 'ecomode':
                state['eco_mode'] = bool(action.get('value', True))
        elif command in {'schedule', 'start'}:
            state['scheduled_period'] = action.get('period', 'Off-Peak')
            state['next_schedule'] = action.get('time_window', 'Next observed Off-Peak window')
    ACTIVE_RULES.append(deepcopy(checked))
    checked['device_states'] = get_device_states()
    return checked
