from pathlib import Path
import csv
from datetime import datetime
DATA_PATH = Path(__file__).resolve().parent / 'sic_iot_dataset.csv'
REQUIRED_COLUMNS = {'home_id', 'timestamp', 'occupied', 'humidity', 'outdoor_temp_c', 'indoor_temp_c', 'hvac_mode', 'heat_set_c', 'cool_set_c', 'hvac_usage_kwh', 'robot_vacuum_usage_kwh', 'washer_dryer_usage_kwh', 'dishwasher_usage_kwh', 'total_usage_kwh', 'price_tou_usd_per_kwh', 'tariff_period', 'cost_usd'}

def validate(path: Path=DATA_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'Place the provided SIC CSV at {path}.')
    with path.open('r', newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'SIC CSV is missing required columns: {sorted(missing)}')
        count = 0
        first = last = None
        homes, periods = (set(), set())
        for row in reader:
            stamp = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M')
            first = first or stamp
            last = stamp
            homes.add(row['home_id'])
            periods.add(row['tariff_period'])
            count += 1
    return {'rows': count, 'first_timestamp': first.isoformat(sep=' ') if first else None, 'last_timestamp': last.isoformat(sep=' ') if last else None, 'home_ids': sorted(homes), 'tariff_periods': sorted(periods)}
if __name__ == '__main__':
    print(validate())
