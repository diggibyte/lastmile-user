# Epiroc Portal

Lightweight Flask portal that renders  order/timeline information along with a Leaflet map. The project is meant for show calculating customer ETA by  integrating Databricks-hosted enriched event data .

## Tech Stack
- Flask + Jinja2 templating
- SQLAlchemy (optionally backed by Databricks Lakehouse)
- Leaflet for route visualization
- Databrikcs ML 


## Getting Started
1. **Install dependencies**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configure environment**
   - Copy `.env.example` (if available) or set the variables listed in `app.py` (`FLASK_SECRET_KEY`, `PGHOST`, `PGDATABASE`, etc.).
   - For local-only mode, you can rely on the bundled `app.db`.
3. **Run the app**
   ```bash
   flask --app app run --debug
   ```
4. Visit http://127.0.0.1:5000/ and log in with the demo credentials defined in `init_db`.

## Database Notes
- `get_engine()` expects Databricks/PG environment variables. When unavailable, consider stubbing event data or adjusting to SQLite.
- Run `init_db()` once (temporarily uncomment at the bottom of `app.py`) to bootstrap tables/users if you want to use the local SQLite DB.

## Troubleshooting
- **Token/auth errors:** ensure `LAKEBASE_INSTANCE_NAME`, `DATABRICKS_HOST`, and `DATABRICKS_TOKEN` are set when targeting Databricks.
- **Leaflet map not loading:** confirm the integrity hashes in `templates/order_details.html` match the Leaflet version.

## Logging
Logs are written to `logs/` via `custom_logger`. Tail these files for debugging:
```bash
tail -f logs/app_*.log
```

## License
Internal demo project—add licensing information if you plan to distribute externally.
