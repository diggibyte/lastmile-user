from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, text, event
import sqlite3
from dotenv import load_dotenv
import os
import uuid
import time
from flask import Flask, render_template
import json
import threading
from pathlib import Path
from databricks.sdk import WorkspaceClient
from custom_logger import logger
import time
from urllib.parse import quote_plus
from datetime import datetime, date
from decimal import Decimal
from datetime import datetime, date
from decimal import Decimal
from traffic_query_helper import get_traffic_update

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-change-me")  # set env var in production

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")

LAKEBASE_INSTANCE_NAME = os.getenv("LAKEBASE_INSTANCE_NAME")

# ============================================================
# Lakebase OAuth tokens expire every 60 minutes.
# This module automatically refreshes tokens every 50 minutes.
# ============================================================

_token_state = {
    "password": None,
    "last_refresh": 0,
    "workspace_client": None,
    "engine": None
}
_token_lock = threading.Lock()


def _get_workspace_client():
    """Get or create WorkspaceClient for Databricks API calls."""
    if _token_state["workspace_client"] is None:
        host = os.getenv("DATABRICKS_HOST")
        token = os.getenv("DATABRICKS_TOKEN")
        
        if host and token:
            # Local development with PAT
            _token_state["workspace_client"] = WorkspaceClient(host=host, token=token)
            logger.info("WorkspaceClient initialized with PAT authentication")
        else:
            # Databricks Apps - auto-authenticates via service principal
            _token_state["workspace_client"] = WorkspaceClient()
            logger.info("WorkspaceClient initialized with auto-authentication")
    
    return _token_state["workspace_client"]


def _generate_oauth_token():
    """Generate a fresh OAuth token for Lakebase connection."""
    w = _get_workspace_client()
    instance_name = LAKEBASE_INSTANCE_NAME
    
    if not instance_name:
        raise ValueError(
            "LAKEBASE_INSTANCE_NAME environment variable is required. "
            "Set it to your Lakebase instance ID (e.g., 'e1c07201-6c30-4306-bbe0-f40d8ebcf2e4')"
        )
    
    try:
        cred = w.database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[instance_name]
        )
        logger.info("Generated new Lakebase OAuth token successfully")
        return cred.token
    except Exception as e:
        logger.error(f"Failed to generate OAuth token: {str(e)}")
        raise


def _refresh_token_if_needed():
    """Refresh token if it's older than 50 minutes (tokens expire at 60 min)."""
    with _token_lock:
        time_since_refresh = time.time() - _token_state["last_refresh"]
        
        if time_since_refresh > 50 * 60 or _token_state["password"] is None:
            logger.info(f"Token refresh needed (age: {time_since_refresh/60:.1f} minutes)")
            _token_state["password"] = _generate_oauth_token()
            _token_state["last_refresh"] = time.time()
        
        return _token_state["password"]


def get_engine():
    """
    Create SQLAlchemy engine with OAuth token authentication.
    """
    global _token_state
    
    # Return cached engine if exists
    if _token_state["engine"] is not None:
        _refresh_token_if_needed()
        return _token_state["engine"]
    
    # Try PGXXX vars first (auto-injected by Databricks Apps), then fallback to DB_XXX
    db_user = os.getenv("PGUSER") or os.getenv("DB_USER")
    db_host = os.getenv("PGHOST") or os.getenv("DB_HOST")
    db_name = os.getenv("PGDATABASE") or os.getenv("DB_NAME")
    
    logger.info(f"Creating database engine: user={db_user}, host={db_host}, db={db_name}")
    
    if not db_host or not db_name:
        raise ValueError(
            "Missing database connection parameters. "
            "Set DB_HOST, DB_NAME (or PGHOST, PGDATABASE for Databricks Apps)"
        )
    
    # Get username if not provided
    if not db_user:
        w = _get_workspace_client()
        db_user = os.getenv("DATABRICKS_CLIENT_ID") or w.current_user.me().user_name
        logger.info(f"Using auto-detected username: {db_user}")
    
    # URL-encode the username (handles @ symbol in email addresses)
    db_user_encoded = quote_plus(db_user)
    
    # Generate initial OAuth token
    _token_state["password"] = os.getenv("DATABRICKS_TOKEN") #_generate_oauth_token()
    _token_state["last_refresh"] = time.time()
    
    # Create engine with placeholder password (event listener will inject real token)
    engine = create_engine(
        f"postgresql+psycopg2://{db_user_encoded}:placeholder@{db_host}:5432/{db_name}"
        "?sslmode=require",
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600
    )
    
    # Event listener to inject fresh token for each new connection
    @event.listens_for(engine, "do_connect")
    def provide_token(dialect, conn_rec, cargs, cparams):
        cparams["password"] = _refresh_token_if_needed()
    
    _token_state["engine"] = engine
    logger.info("Database engine created successfully with OAuth authentication")
    return engine


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id     TEXT UNIQUE NOT NULL,
            shipping_id     TEXT UNIQUE NOT NULL,
            status  TEXT NOT NULL,
            actual_event_ts TIMESTAMP DEFAULT NULL,
            estimated_event_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            city_location Text,
            longitute  REAL,
            latitude REAL 
        )
    """)
    conn.commit()

    # Create a default user if none exist
    cur.execute("SELECT COUNT(*) AS c FROM users")
    count = cur.fetchone()["c"]
    if count == 1:
        # Default credentials: admin / Admin123!
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("Amit", generate_password_hash("Amit123!"))
        )
        conn.commit()


    #cur.execute(
    #"INSERT INTO events VALUES ('ORD-2001','SHIP-2001-01','ORDER_PLACED',NULL,'2024-01-05 09:00:00','Order placed and shipment planning initiated','Los Angeles, CA',118.2437,34.0522)")
    conn.close()


def current_user():
    return session.get("username")


def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


@app.route("/")
@login_required
def home():
    return render_template("home.html", username=current_user())


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("home"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
       
        password = request.form.get("password") or ""
        print(password)

        if not username or not password:
            flash("Please enter both username and password.", "error")
            return render_template("login.html")

        # conn = get_db()
        # cur = conn.cursor()
        # print(username)
        # cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        # user = cur.fetchone()
        # print(user)
        # conn.close()

        if 1==1:
            session["username"] = username
            return redirect(url_for("home"))
        #if user and check_password_hash(user["password_hash"], password):
        #    session["username"] = username
         #   return redirect(url_for("home"))

        flash("Invalid username or password.", "error")
        return render_template("login.html")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return {"status": "ok"}


DATA_DIR = Path(__file__).parent / "data"


def _serialize_value(value):
    """Convert DB values into JSON-serializable primitives."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


@app.route("/my-orders")
def my_orders():
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("select * from orders")
            ).mappings().all()
    except Exception as e:
        logger.error(f"Database error fetching tasks: {str(e)}")
        rows = []

    image_dir = Path(app.static_folder or "static") / "img"
    available_images = {}
    if image_dir.exists():
        for image_path in image_dir.glob("*.*"):
            if image_path.is_file():
                available_images[image_path.stem.upper()] = image_path.name

    fallback_image = "image.png"
    orders = []
    for row in rows:
        order_data = dict(row)
        product_id_value = order_data.get("product_id")
        raw_code = str(product_id_value).strip() if product_id_value is not None else ""
        normalized_code = raw_code.upper()
        image_name = available_images.get(normalized_code, fallback_image)
        order_data["product_code"] = raw_code or "N/A"
        order_data["product_image"] = image_name
        orders.append(order_data)

    return render_template("my_orders.html", orders=orders)


@app.route("/products")
def all_products():
    # Placeholder "view all products"
    products = [
        # load full product list here
    ]
    return render_template("all_products.html", products=products)


@app.route("/orders/<order_id>")
def order_details(order_id):
    # Example order; normally load from DB
    try:
        with get_engine().connect() as conn:
            order = conn.execute(
                text(f"select * from orders where order_id = '{order_id}'")
            ).fetchone()
           
    except Exception as e:
        logger.error(f"Database error fetching tasks: {str(e)}")
        order = []
   
    order = {
        "id": order.order_id,
        "placed_date": order.placed_date,
        "status": order.status,
        "total": f"${order.total_amount}",
        "traffic_status": round(int(get_traffic_update(order.origin_latitude , order.origin_longitude,order.destination_latitude, order.destination_longitude)["traffic_delay_min"])/60,2)
    }

    # Timeline events loaded from file: data/orders/<order_id>.json
    try:
        with get_engine().connect() as conn:
            events = conn.execute(
                text(f"select * from events where order_id = '{order_id}'")
            ).mappings().all()
           
    except Exception as e:
        logger.error(f"Database error fetching tasks: {str(e)}")
        events = []
    

       

    events = [
        {
            key: _serialize_value(value)
            for key, value in dict(event).items()
        }
        for event in events
        if event.get("order_id") == order_id
    ]

    estimated_eta = "TBD"
    if events:
        for event in reversed(events):
            est = event.get("estimated_event_ts")
            if est and est != "null":
                estimated_eta = est
                break

    status_confidence = {
        "Delivered": "Confirmed (100%)",
        "In Transit": "High (85%)",
        "Placed": "Planned (70%)",
        "Order Placed": "Planned (70%)",
    }
    eta_confidence = status_confidence.get(order["status"], "Medium (60%)")

    order["estimated_eta"] = estimated_eta
    order["eta_confidence"] = eta_confidence

    return render_template("order_details.html", order=order, events=events)
# ...existing code...




if __name__ == "__main__":
    #init_db()
    app.run(debug=True)
