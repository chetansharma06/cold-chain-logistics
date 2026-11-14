# Cold-chain logistics project setup

## Configure the environment

1. If `.env` does not exist, copy `.env.storage.example` to `.env`. For an existing file, merge the settings and preserve its provider keys.
2. Set `GEMINI_API_KEY` and `Agent_llm=GEMINI` to use Gemini.
3. SOP lookup also needs `PINECONE_API_KEY`. Local embeddings download the configured model when first used.
4. Set `AUDIT_ADMIN_USERNAME` and `AUDIT_ADMIN_PASSWORD` for the audit-log page. Do not commit `.env` or share its secrets.

Telemetry and audit events are stored locally as JSON Lines files:

- `data/telemetry.jsonl`
- `data/audit_log.jsonl`

Set `TELEMETRY_STORE_PATH` or `AUDIT_STORE_PATH` in `.env` to move either file. Relative paths are resolved from the project root.

## Create and install the virtual environment

Use Python 3.11 on Windows:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The VS Code workspace is configured to select this interpreter and activate it in new PowerShell terminals. The real activation script displays `(venv)` in green. If script execution is blocked by your machine's PowerShell policy, follow your organization's approved policy rather than bypassing it.

## Load the telemetry data

From the project root, run:

```powershell
python scripts\ingest_legacy_data.py
```

The importer reads `data\raw\dynamic_supply_chain_logistics_dataset.csv`, keeps the telemetry fields used by the agent, and writes one document per line. It refuses to overwrite an existing telemetry file. To preserve existing data, choose a different `TELEMETRY_STORE_PATH` for a separate import.

## Start the application

```powershell
streamlit run src\ui.py
```

Fleet questions use `query_telemetry` with structured filters for risk classification, location ranges, temperature, and delay probability. Weather lookup and compliance-document search remain available as separate tools.

The Security & Audit Logs page uses the local audit file. Configure its username and password in `.env` before using that page.

## Run tests

```powershell
python -m unittest discover -s tests -v
```
