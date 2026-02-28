from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
import hashlib
import requests

app = Flask(__name__)
app.secret_key = "weather_secret_2024"

# Replace "demo" with a free API key from openweathermap.org
API_KEY = "bd0640a8b8a7760f69014adaf80a1f2d"


#DATABASE

def get_db():
    """Connect to the database and return the connection."""
    con = sqlite3.connect("weather.db")
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Create tables and add demo users if the database is empty."""
    con = get_db()
    c = con.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role     TEXT NOT NULL DEFAULT 'user'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS cities (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name    TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Only add demo data if the users table is empty
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        user_pw  = hashlib.sha256("user123".encode()).hexdigest()
        admin_pw = hashlib.sha256("admin123".encode()).hexdigest()

        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ("demo", user_pw, "user"))
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ("admin", admin_pw, "admin"))

        # few cities for the demo account
        c.execute("INSERT INTO cities (user_id, name, country) VALUES (1, 'Riga', 'LV')")
        c.execute("INSERT INTO cities (user_id, name, country) VALUES (1, 'London', 'GB')")
        c.execute("INSERT INTO cities (user_id, name, country) VALUES (1, 'Tokyo', 'JP')")

    con.commit()
    con.close()


# weather API

def get_weather(city, country=""):
    """
    Fetch weather data from OpenWeatherMap.
    Returns a dictionary with weather info, or an error message.
    If API_KEY is 'demo', returns fake data for testing.
    """

    # Demo mode
    if API_KEY == "demo":
        fake = {
            "Riga":   {"temp": 8,  "desc": "Cloudy",       "wind": 5.2, "humidity": 78, "icon": "04d"},
            "London": {"temp": 12, "desc": "Light rain",   "wind": 7.1, "humidity": 85, "icon": "10d"},
            "Berlin": {"temp": 6,  "desc": "Clear sky",    "wind": 3.4, "humidity": 60, "icon": "01d"},
            "Tokyo":  {"temp": 18, "desc": "Partly cloudy","wind": 2.1, "humidity": 72, "icon": "02d"},
            "Paris":  {"temp": 15, "desc": "Mist",         "wind": 4.0, "humidity": 65, "icon": "50d"},
        }
        data = fake.get(city, {"temp": 10, "desc": "Unknown", "wind": 0, "humidity": 50, "icon": "01d"})
        return {"city": city, "temp": data["temp"], "desc": data["desc"],
                "wind": data["wind"], "humidity": data["humidity"], "icon": data["icon"], "error": None}

    #API call
    try:
        query = f"{city},{country}" if country else city
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": query, "appid": API_KEY, "units": "metric"},
            timeout=5
        )
        if response.status_code == 200:
            d = response.json()
            return {
                "city":     d["name"],
                "temp":     round(d["main"]["temp"]),
                "desc":     d["weather"][0]["description"].capitalize(),
                "wind":     d["wind"]["speed"],
                "humidity": d["main"]["humidity"],
                "icon":     d["weather"][0]["icon"],
                "error":    None
            }
        elif response.status_code == 404:
            return {"error": f"City '{city}' not found."}
        else:
            return {"error": "API error. Check your API key."}

    except Exception as e:
        return {"error": f"Connection error: {e}"}


@app.route("/")
def home():
    if "id" in session:
        return redirect("/dashboard")
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = hashlib.sha256(request.form.get("password", "").encode()).hexdigest()

        con = get_db()
        user = con.execute(
            "SELECT * FROM users WHERE username = ? AND password = ?", (username, password)
        ).fetchone()
        con.close()

        if user:
            session["id"]       = user["id"]
            session["username"] = user["username"]
            session["role"]     = user["role"]
            return redirect("/dashboard")
        else:
            return render_template("login.html", error="Wrong username or password.")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if len(username) < 3:
            return render_template("register.html", error="Username must be at least 3 characters.")
        if len(password) < 6:
            return render_template("register.html", error="Password must be at least 6 characters.")

        try:
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            con = get_db()
            con.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, pw_hash))
            con.commit()
            new_id = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]
            con.close()

            session["id"]       = new_id
            session["username"] = username
            session["role"]     = "user"
            return redirect("/dashboard")

        except sqlite3.IntegrityError:
            return render_template("register.html", error="That username is already taken.")

    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/dashboard")
def dashboard():
    if "id" not in session:
        return redirect("/login")

    con = get_db()
    cities = con.execute("SELECT * FROM cities WHERE user_id = ?", (session["id"],)).fetchall()
    con.close()

    # Build a list of weather dicts - one per saved city
    weather_list = []
    for city in cities:
        data = get_weather(city["name"], city["country"])
        data["db_id"] = city["id"]
        weather_list.append(data)

    return render_template("dashboard.html", weather_list=weather_list)


@app.route("/add", methods=["POST"])
def add_city():
    if "id" not in session:
        return redirect("/login")

    name    = request.form.get("name", "").strip()
    country = request.form.get("country", "").strip().upper()

    if not name:
        return redirect("/dashboard")

    # Check the city actually exists before saving
    check = get_weather(name, country)
    if check.get("error"):
        con = get_db()
        cities = con.execute("SELECT * FROM cities WHERE user_id = ?", (session["id"],)).fetchall()
        con.close()
        weather_list = []
        for city in cities:
            data = get_weather(city["name"], city["country"])
            data["db_id"] = city["id"]
            weather_list.append(data)
        return render_template("dashboard.html", weather_list=weather_list, error=check["error"])

    # Don't add duplicates
    con = get_db()
    exists = con.execute(
        "SELECT id FROM cities WHERE user_id = ? AND LOWER(name) = LOWER(?)",
        (session["id"], name)
    ).fetchone()

    if not exists:
        con.execute("INSERT INTO cities (user_id, name, country) VALUES (?, ?, ?)",
                    (session["id"], check["city"], country))
        con.commit()
    con.close()

    return redirect("/dashboard")


@app.route("/delete/<int:city_id>")
def delete_city(city_id):
    if "id" not in session:
        return redirect("/login")

    con = get_db()
    # Only delete if the city belongs to the logged-in user
    con.execute("DELETE FROM cities WHERE id = ? AND user_id = ?", (city_id, session["id"]))
    con.commit()
    con.close()

    return redirect("/dashboard")


@app.route("/admin")
def admin():
    if "id" not in session or session["role"] != "admin":
        return redirect("/login")

    con = get_db()
    # Get all users with their city count using a JOIN
    users = con.execute("""
        SELECT u.id, u.username, u.role, COUNT(c.id) as city_count
        FROM users u
        LEFT JOIN cities c ON u.id = c.user_id
        GROUP BY u.id
    """).fetchall()
    total_cities = con.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    con.close()

    return render_template("admin.html", users=users, total_cities=total_cities)


@app.route("/api/weather")
def weather_api():
    """JSON endpoint - returns weather data for a city. Example: /api/weather?city=Riga&country=LV"""
    city    = request.args.get("city", "")
    country = request.args.get("country", "")
    if not city:
        return jsonify({"error": "Missing parameter: city"})
    return jsonify(get_weather(city, country))


if __name__ == "__main__":
    init_db()
    print("Weather Dashboard running at http://localhost:5000")
    print("Demo accounts:  demo / user123   |   admin / admin123")
    app.run(debug=True, port=5000)
