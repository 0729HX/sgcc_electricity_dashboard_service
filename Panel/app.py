import os
import pymysql
from flask import Flask, jsonify, render_template, request

def load_options():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    if not os.path.exists(config_path):
        return {}
    options = {}
    in_options = False
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("options:"):
                in_options = True
                continue
            if in_options:
                if not line.startswith("  "):
                    break
                parts = stripped.split(":", 1)
                if len(parts) != 2:
                    continue
                key = parts[0].strip()
                value = parts[1].strip()
                if " #" in value:
                    value = value.split(" #", 1)[0].strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                options[key] = value
    return options

def init_env():
    options = load_options()
    for key in [
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DB",
        "DB_NAME",
    ]:
        if key in options:
            os.environ[key] = str(options[key])

def get_db():
    host = os.getenv("MYSQL_HOST", "192.168.1.223")
    port = int(os.getenv("MYSQL_PORT", 3306))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "root")
    db_name = os.getenv("MYSQL_DB", os.getenv("DB_NAME", "sgcc_electricity"))
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db_name,
        charset="utf8mb4",
        autocommit=True,
    )

def load_dashboard_data():
    conn = get_db()
    cursor = conn.cursor()
    yearly = {}
    cursor.execute(
        "SELECT `user_id`, `balance`, `last_daily_date`, `last_daily_usage`, `total_usage`, `total_charge` "
        "FROM yearly_stats ORDER BY `year` DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row:
        yearly = {
            "user_id": row[0],
            "balance": float(row[1]) if row[1] is not None else 0,
            "last_daily_date": row[2].strftime("%Y-%m-%d") if row[2] is not None else "",
            "last_daily_usage": float(row[3]) if row[3] is not None else 0,
            "total_usage": float(row[4]) if row[4] is not None else 0,
            "total_charge": float(row[5]) if row[5] is not None else 0,
        }
    cursor.execute("SELECT `date`, `usage` FROM daily_usage ORDER BY `date` ASC")
    daily = []
    for d, u in cursor.fetchall():
        daily.append([d.strftime("%Y-%m-%d"), float(u) if u is not None else 0])
    cursor.execute(
        "SELECT `year`, `month`, `usage`, `charge` FROM monthly_stats ORDER BY `year` ASC, `month` ASC"
    )
    monthly = []
    for y, m, u, c in cursor.fetchall():
        ym = f"{int(y):04d}-{int(m):02d}"
        monthly.append(
            {"month": ym, "usage": float(u) if u is not None else 0, "charge": float(c) if c is not None else 0}
        )
    conn.close()
    return {"yearly": yearly, "daily": daily, "monthly": monthly}

def create_app():
    init_env()
    app = Flask(__name__, template_folder="templates")

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/stats/overview")
    def api_overview():
        data = load_dashboard_data()
        yearly = data.get("yearly") or {}
        return jsonify(
            {
                "balance": yearly.get("balance", 0),
                "last_daily_usage": yearly.get("last_daily_usage", 0),
                "last_daily_date": yearly.get("last_daily_date", ""),
                "total_usage": yearly.get("total_usage", 0),
                "total_charge": yearly.get("total_charge", 0),
            }
        )

    @app.route("/api/stats/daily")
    def api_daily():
        try:
            days = int(request.args.get("days", "30"))
        except ValueError:
            days = 30
        days = max(1, min(days, 365))
        data = load_dashboard_data()
        daily = data.get("daily") or []
        if days > 0 and len(daily) > days:
            daily = daily[-days:]
        return jsonify([{"date": d, "usage": u} for d, u in daily])

    @app.route("/api/stats/monthly")
    def api_monthly():
        data = load_dashboard_data()
        monthly = data.get("monthly") or []
        if monthly:
            return jsonify(
                [
                    {
                        "month": m["month"],
                        "usage": m.get("usage", 0),
                        "charge": m.get("charge", 0),
                    }
                    for m in monthly
                ]
            )
        daily = data.get("daily") or []
        agg = {}
        for d, u in daily:
            ym = d[:7]
            agg[ym] = agg.get(ym, 0) + (u or 0)
        return jsonify([{"month": k, "usage": round(v, 2)} for k, v in sorted(agg.items())])

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
