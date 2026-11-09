# Smart_Things_Assistant

This is a separate, CSV-aligned edition of the SIC SmartThings assistant. It reads the supplied hourly household dataset directly and keeps its units and limits visible throughout the analytics.

Each executable Python or PowerShell script has its own explanation file under `docs/scripts/`. The scripts contain no explanatory comments or docstrings; the separate files document their purpose and behavior.

## Dataset used

`data/sic_iot_dataset.csv` is a copy of `PJ3_Energy Saving - sic_IoT_dataset.csv`. It has 5,832 hourly observations for `HOME-JAMES-001`, from 2025-01-01 through 2025-08-31. The app uses the observed `total_usage_kwh`, appliance-category kWh, `outdoor_temp_c`, `indoor_temp_c`, occupancy, tariff period, USD/kWh price, and `cost_usd` columns. Setup validates this source file; it does not generate substitute telemetry.

The source has no refrigerator channel, smart plug readings, device model metadata, or solar measurements. The dashboard and compiler avoid claiming those are available. Overnight baseline is shown at whole-home level, and appliance scheduling uses the observed Peak/Off-Peak tariff fields.

## Run on Windows PowerShell

```powershell
cd .\Smart_Things_Assistant
.\setup.ps1
```

Open two PowerShell windows in the project directory and run:

```powershell
.\run_api.ps1
```

```powershell
.\run_ui.ps1
```

The API is at `http://127.0.0.1:8000` (`/docs` for the interactive schema). Streamlit falls back to direct local backend imports when the API is unavailable. Set `$env:GEMINI_API_KEY` to enable Gemini 2.5 Flash; the deterministic CSV-aware compiler works offline.

## API endpoints

- `GET /telemetry`: dataset summary, recent hourly energy/category series, anomalies, tariff/weather recommendations, and virtual device states.
- `POST /simulate`: 30-day energy and USD cost projection with comfort weighting.
- `POST /chat-compile`: CSV-aware natural-language routine compiler.
- `POST /execute-rule`: apply an approved routine to the virtual state; comfort-sensitive and protected actions require confirmation.
