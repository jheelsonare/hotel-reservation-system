"""Indian Hotel Management System - Flask/MySQL application."""
import os
import secrets
import hmac
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from collections import OrderedDict, deque
from threading import Lock
from time import monotonic
from urllib.parse import urlencode

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from mysql.connector import Error

load_dotenv()
app = Flask(__name__)
# A missing key gets a cryptographically random per-process key, never a known fallback.
configured_secret = os.getenv("SECRET_KEY", "")
if configured_secret and (len(configured_secret) < 32 or configured_secret in (
    "change-this-secret", "replace-with-a-random-secret",
)):
    raise RuntimeError("SECRET_KEY must be a new random value of at least 32 characters")
app.secret_key = configured_secret or secrets.token_hex(32)
app.config.update(
    ADMIN_USERNAME=os.getenv("ADMIN_USERNAME", "admin"),
    ADMIN_PASSWORD_HASH=os.getenv("ADMIN_PASSWORD_HASH", ""),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=64 * 1024,
)
_auth_failures = OrderedDict()
_auth_lock = Lock()


@app.before_request
def require_admin():
    """Protect every database-facing route; missing configuration fails closed."""
    password_hash = app.config.get("ADMIN_PASSWORD_HASH", "")
    if not password_hash:
        return Response("Administrator access is not configured. Set ADMIN_PASSWORD_HASH.", status=503)
    auth = request.authorization
    if not auth or auth.type.lower() != "basic":
        return Response("Sign in to manage hotel records.", status=401,
                        headers={"WWW-Authenticate": 'Basic realm="Hotel administration", charset="UTF-8"'})
    address, now = request.remote_addr or "unknown", monotonic()
    with _auth_lock:
        failures = _auth_failures.setdefault(address, deque())
        while failures and failures[0] <= now - 60:
            failures.popleft()
        if len(failures) >= 5:
            return Response("Too many sign-in attempts. Try again in one minute.", status=429,
                            headers={"Retry-After": "60"})
    try:
        valid = (hmac.compare_digest((auth.username or "").encode(),
                                     app.config["ADMIN_USERNAME"].encode())
                 and check_password_hash(password_hash, auth.password or ""))
    except (ValueError, TypeError):
        return Response("Administrator password hash is invalid.", status=503)
    with _auth_lock:
        if valid:
            _auth_failures.pop(address, None)
        else:
            _auth_failures.setdefault(address, deque()).append(now)
            _auth_failures.move_to_end(address)
            while len(_auth_failures) > 1024:
                _auth_failures.popitem(last=False)
    if not valid:
        return Response("Invalid sign-in details.", status=401,
                        headers={"WWW-Authenticate": 'Basic realm="Hotel administration", charset="UTF-8"'})


@app.after_request
def protect_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "hotel_app"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "hotel_db"),
}
PAGE_SIZE = 25
ENTITIES = {
    "guests": ("Guest", "guest_id", ["name", "phone", "email", "city", "state", "id_proof_type", "id_proof_no"]),
    "hotels": ("Hotel", "hotel_id", ["hotel_name", "address", "city", "manager_name"]),
    "rooms": ("Room", "room_id", ["hotel_id", "type_id", "room_no", "capacity", "status"]),
    "reservations": ("Reservation", "reservation_id", ["guest_id", "room_id", "check_in", "check_out", "status"]),
    "payments": ("Payment", "payment_id", ["reservation_id", "amount", "payment_date", "mode"]),
}
FIELD_CHOICES = {
    ("rooms", "status"): ["Available", "Maintenance"],
    ("reservations", "status"): ["Booked", "Checked-in", "Cancelled", "Completed"],
    ("payments", "mode"): ["Cash", "UPI", "Card", "Net Banking"],
}


def connection():
    conn = mysql.connector.connect(
        **DB_CONFIG, connection_timeout=5, autocommit=False, charset="utf8mb4",
        sql_mode="STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION",
    )
    try:
        cur = conn.cursor()
        cur.execute("SET SESSION max_execution_time=5000, innodb_lock_wait_timeout=5")
        cur.close()
        return conn
    except Error:
        conn.close()
        raise


def query(sql, params=(), one=False, dictionary=True):
    conn = cur = None
    try:
        conn = connection()
        cur = conn.cursor(dictionary=dictionary)
        cur.execute(sql, params)
        rows = cur.fetchone() if one else cur.fetchall()
        return rows
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def execute(sql, params=()):
    conn = cur = None
    try:
        conn = connection()
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    except Error:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def write_guest(cur, values, item_id=None):
    """Resolve a city/state pair and write its FK in the caller's transaction."""
    name, phone, email, city, state, proof_type, proof_no = values
    cur.execute(
        """INSERT INTO Location (city, state) VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE location_id=LAST_INSERT_ID(location_id)""",
        (city, state),
    )
    location_id = cur.lastrowid
    guest_values = (name, phone, email, location_id, proof_type, proof_no)
    if item_id is None:
        cur.execute(
            """INSERT INTO Guest
            (name, phone, email, location_id, id_proof_type, id_proof_no)
            VALUES (%s, %s, %s, %s, %s, %s)""", guest_values,
        )
        return cur.lastrowid
    cur.execute(
        """UPDATE Guest SET name=%s, phone=%s, email=%s, location_id=%s,
        id_proof_type=%s, id_proof_no=%s WHERE guest_id=%s""",
        guest_values + (item_id,),
    )
    return item_id


def save_guest(values, item_id=None):
    conn = cur = None
    try:
        conn = connection()
        cur = conn.cursor()
        guest_id = write_guest(cur, values, item_id)
        conn.commit()
        return guest_id
    except Error:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def safe_db(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Error as exc:
            app.logger.warning("Database operation failed (errno=%s)", exc.errno)
            flash("The database could not complete that operation. Please check the values and try again.", "error")
            return redirect(url_for("dashboard"))
    return wrapped


@app.template_filter("money")
def money(value):
    number = Decimal(str(value or 0))
    integer, _, fraction = f"{number:.2f}".partition(".")
    sign = "-" if integer.startswith("-") else ""
    digits = integer.lstrip("-")
    if len(digits) > 3:
        last = digits[-3:]
        head = digits[:-3]
        groups = []
        while head:
            groups.insert(0, head[-2:])
            head = head[:-2]
        digits = ",".join(groups + [last])
    return f"Rs {sign}{digits}.{fraction}"


@app.template_filter("date_dmy")
def date_dmy(value):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return value
    return value.strftime("%d-%m-%Y")


@app.context_processor
def globals_for_templates():
    return {"today": date.today().isoformat(), "entities": ENTITIES}


@app.context_processor
def csrf_for_templates():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return {"csrf_token": token}


def valid_csrf():
    token = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(token and expected and hmac.compare_digest(token, expected))


@app.route("/")
def dashboard():
    counts = {"guests": 0, "rooms": 0, "available_rooms": 0,
              "active_reservations": 0, "revenue": 0}
    try:
        counts["guests"] = query("SELECT COUNT(*) n FROM guest_details_view", one=True)["n"]
        counts["rooms"] = query("SELECT COUNT(*) n FROM Room", one=True)["n"]
        counts["available_rooms"] = query("SELECT COUNT(*) n FROM available_rooms_view", one=True)["n"]
        counts["active_reservations"] = query(
            "SELECT COUNT(*) n FROM Reservation WHERE status IN ('Booked','Checked-in')",
            one=True)["n"]
        counts["revenue"] = query("SELECT COALESCE(SUM(amount),0) n FROM Payment", one=True)["n"]
    except Error:
        flash("Unable to load dashboard statistics. Check the MySQL connection.", "error")
    upcoming = []
    try:
        upcoming = query("""SELECT r.reservation_id, c.name, h.hotel_name, rm.room_no,
            r.check_in, r.check_out, r.status
            FROM Reservation r JOIN guest_details_view c ON c.guest_id=r.guest_id
            JOIN Room rm ON rm.room_id=r.room_id JOIN Hotel h ON h.hotel_id=rm.hotel_id
            WHERE r.check_out >= CURDATE() AND r.status <> 'Cancelled'
            ORDER BY r.check_in LIMIT 8""")
    except Error:
        pass
    try:
        bookings_chart = query("""SELECT h.hotel_name label, COUNT(r.reservation_id) value
            FROM Hotel h JOIN Room rm ON rm.hotel_id=h.hotel_id
            LEFT JOIN Reservation r ON r.room_id=rm.room_id
            GROUP BY h.hotel_id, h.hotel_name ORDER BY value DESC LIMIT 20""")
        revenue_chart = query("""SELECT mode label, COALESCE(SUM(amount),0) value
            FROM Payment GROUP BY mode ORDER BY value DESC LIMIT 20""")
    except Error:
        bookings_chart, revenue_chart = [], []
    return render_template("index.html", counts=counts, upcoming=upcoming,
                           bookings_chart=bookings_chart, revenue_chart=revenue_chart)


def page_data(key):
    table, pk, fields = ENTITIES[key]
    page = max(request.args.get("page", 1, type=int), 1)
    search = request.args.get("q", "").strip()[:200]
    sort = request.args.get("sort", pk)
    if sort not in fields + [pk]:
        sort = pk
    where, params = "", []
    from_sql = "guest_details_view" if key == "guests" else f"`{table}`"
    alias = ""
    if key == "reservations":
        from_sql = "Reservation r JOIN Room rm ON rm.room_id=r.room_id"
        alias = "r."
    if search:
        where = " WHERE (" + " OR ".join(
            f"CAST({alias}`{f}` AS CHAR) LIKE %s" for f in fields
        ) + ")"
        params = [f"%{search}%"] * len(fields)
    clauses = []
    if key == "reservations":
        status = request.args.get("status", "")
        hotel = request.args.get("hotel", type=int)
        start = request.args.get("start", "")
        end = request.args.get("end", "")
        if status:
            clauses.append("r.status=%s"); params.append(status)
        if hotel:
            clauses.append("rm.hotel_id=%s"); params.append(hotel)
        if start:
            clauses.append("r.check_in >= %s"); params.append(start)
        if end:
            clauses.append("r.check_out <= %s"); params.append(end)
        if clauses:
            where = (" WHERE " if not where else where + " AND ") + " AND ".join(clauses)
    total = query(f"SELECT COUNT(*) AS n FROM {from_sql}{where}", params, one=True)["n"]
    offset = (page - 1) * PAGE_SIZE
    select_sql = "SELECT r.*" if key == "reservations" else "SELECT *"
    order_column = f"{alias}`{sort}`"
    if key == "rooms" and sort == "room_no":
        order_column = "CAST(`room_no` AS UNSIGNED)"
    rows = query(f"{select_sql} FROM {from_sql}{where} ORDER BY {order_column}, {alias}`{pk}` LIMIT %s OFFSET %s",
                 params + [PAGE_SIZE, offset])
    extra = {"status": request.args.get("status", ""), "hotel": request.args.get("hotel", ""),
             "start": request.args.get("start", ""), "end": request.args.get("end", "")}
    query_args = {"q": search, "sort": sort, **{k: v for k, v in extra.items() if v}}
    return (table, pk, fields, rows, page, (total + PAGE_SIZE - 1) // PAGE_SIZE,
            search, sort, extra, total, urlencode(query_args))


@app.route("/<key>")
@safe_db
def listing(key):
    if key not in ENTITIES:
        return redirect(url_for("dashboard"))
    data = page_data(key)
    values = dict(zip(("table", "pk", "fields", "rows", "page", "pages", "search", "sort", "filters", "total", "query_string"), data))
    values["hotels"] = query("SELECT hotel_id, hotel_name FROM Hotel ORDER BY hotel_name") if key == "reservations" else []
    values["field_choices"] = FIELD_CHOICES
    return render_template("list.html", key=key, **values)


@app.route("/<key>/new", methods=["GET", "POST"])
@app.route("/<key>/<int:item_id>/edit", methods=["GET", "POST"])
@safe_db
def edit(key, item_id=None):
    if key not in ENTITIES:
        return redirect(url_for("dashboard"))
    table, pk, fields = ENTITIES[key]
    read_table = "guest_details_view" if key == "guests" else table
    record = query(f"SELECT * FROM `{read_table}` WHERE `{pk}`=%s", (item_id,), one=True) if item_id else {}
    if item_id and not record:
        flash(f"{table} not found.", "error")
        return redirect(url_for("listing", key=key))
    if request.method == "POST":
        if not valid_csrf():
            flash("Your form expired. Please try again.", "error")
            return redirect(request.url)
        values = [request.form.get(field, "").strip() or None for field in fields]
        error = validate(key, values, existing=record)
        if error:
            flash(error, "error")
        else:
            if key == "guests":
                save_guest(values, item_id)
            elif item_id:
                if key == "payments":
                    values[1] = format(Decimal(values[1]), ".2f")
                execute(f"UPDATE `{table}` SET " + ", ".join(f"`{f}`=%s" for f in fields) +
                        f" WHERE `{pk}`=%s", values + [item_id])
            else:
                if key == "payments":
                    values[1] = format(Decimal(values[1]), ".2f")
                execute(f"INSERT INTO `{table}` (" + ",".join(f"`{f}`" for f in fields) +
                        ") VALUES (" + ",".join(["%s"] * len(fields)) + ")", values)
            flash(f"{table} saved.", "success")
            return redirect(url_for("listing", key=key))
    foreign_options = {}
    if key == "rooms":
        foreign_options[("rooms", "hotel_id")] = query("SELECT hotel_id id, hotel_name label FROM Hotel ORDER BY hotel_name")
        foreign_options[("rooms", "type_id")] = query("SELECT type_id id, type_name label FROM RoomType ORDER BY type_name")
    elif key == "reservations":
        foreign_options[("reservations", "guest_id")] = query("SELECT guest_id id, CONCAT(name, ' (#', guest_id, ')') label FROM guest_details_view ORDER BY name, guest_id")
        foreign_options[("reservations", "room_id")] = query("SELECT room_id id, CONCAT(room_no, ' (#', room_id, ')') label FROM Room ORDER BY CAST(room_no AS UNSIGNED), room_id")
    elif key == "payments":
        foreign_options[("payments", "reservation_id")] = query("SELECT reservation_id id, CONCAT('#', reservation_id, ' ', check_in, ' to ', check_out) label FROM Reservation ORDER BY check_in DESC, reservation_id DESC")
    return render_template("form.html", key=key, table=table, pk=pk, fields=fields,
                           record=record, item_id=item_id,
                           field_choices=FIELD_CHOICES, foreign_options=foreign_options)


def parse_form_date(value):
    parsed = date.fromisoformat(value or "")
    if parsed.year < 1000 or parsed.isoformat() != value:
        raise ValueError("Use YYYY-MM-DD dates")
    return parsed


def validate(key, values, existing=None):
    import re
    fields = ENTITIES[key][2]
    data = dict(zip(fields, values))
    limits = {"name": 120, "phone": 10, "email": 160, "city": 80, "state": 80,
              "id_proof_type": 40, "id_proof_no": 40, "hotel_name": 120,
              "address": 255, "manager_name": 120, "room_no": 20}
    for field, value in data.items():
        if value is None and field != "email":
            return f"{field.replace('_', ' ').title()} is required."
        if field in limits and value is not None and len(value) > limits[field]:
            return f"{field.replace('_', ' ').title()} is too long."
        if field.endswith("_id") or field == "capacity":
            digits = str(value or "")
            max_digits, maximum = (3, 255) if field == "capacity" else (10, 2147483647)
            if (len(digits) > max_digits or not re.fullmatch(r"[0-9]+", digits)
                    or not 1 <= int(digits) <= maximum):
                return f"Enter a valid positive {field.replace('_', ' ')}."
    if key == "guests":
        if not re.fullmatch(r"[6-9][0-9]{9}", str(data["phone"])):
            return "Phone must be a 10-digit Indian mobile number starting with 6-9."
        if data["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", data["email"]):
            return "Enter a valid email address."
    for (entity, field), choices in FIELD_CHOICES.items():
        if entity == key and data[field] not in choices:
            return f"Choose a valid {field.replace('_', ' ')}."
    if key == "reservations":
        try:
            check_in, check_out = parse_form_date(data["check_in"]), parse_form_date(data["check_out"])
        except (ValueError, TypeError):
            return "Enter valid check-in and check-out dates (YYYY-MM-DD)."
        if check_in >= check_out:
            return "Check-out must be after check-in."
        unchanged_start = existing and str(existing.get("check_in")) == data["check_in"]
        if data["status"] in ("Booked", "Checked-in") and check_in < date.today() and not unchanged_start:
            return "Active reservations cannot start in the past."
    if key == "payments":
        try:
            amount = Decimal(data["amount"])
            if not amount.is_finite() or amount < 0 or amount > Decimal("99999999.99") or amount != amount.quantize(Decimal("0.01")):
                raise ValueError
        except (InvalidOperation, ValueError, TypeError):
            return "Amount must be between 0 and 99999999.99 with at most two decimal places."
        try:
            parse_form_date(data["payment_date"])
        except (ValueError, TypeError):
            return "Enter a valid payment date (YYYY-MM-DD)."
    return None


@app.post("/<key>/<int:item_id>/delete")
@safe_db
def delete(key, item_id):
    if not valid_csrf():
        flash("Your form expired. Please try again.", "error")
        return redirect(url_for("listing", key=key))
    if key in ENTITIES:
        table, pk, _ = ENTITIES[key]
        try:
            execute(f"DELETE FROM `{table}` WHERE `{pk}`=%s", (item_id,))
        except Error as exc:
            if getattr(exc, "errno", None) == 1451:
                flash("This record has related history and cannot be deleted.", "error")
                return redirect(url_for("listing", key=key))
            raise
        flash("Record deleted.", "success")
    return redirect(url_for("listing", key=key))


@app.route("/reservations/book", methods=["GET", "POST"])
@safe_db
def book():
    if request.method == "POST":
        if not valid_csrf():
            flash("Your form expired. Please try again.", "error")
            return redirect(url_for("book"))
        guest_id = request.form.get("guest_id", type=int)
        new_guest = request.form.get("new_guest") == "1"
        room_type_id = request.form.get("room_type_id", type=int)
        check_in, check_out = request.form.get("check_in"), request.form.get("check_out")
        date_error = None
        try:
            parse_form_date(check_in)
            parse_form_date(check_out)
        except (ValueError, TypeError):
            date_error = "Enter valid check-in and check-out dates (YYYY-MM-DD)."
        guest_error = None
        guest_values = None
        if new_guest:
            guest_values = [
                request.form.get(field, "").strip() or None
                for field in ("guest_name", "guest_phone", "guest_email", "guest_city",
                              "guest_state", "guest_id_proof_type", "guest_id_proof_no")
            ]
            guest_error = validate("guests", guest_values)
            if guest_error:
                flash(guest_error, "error")
        if (not guest_id and not new_guest) or not room_type_id or not check_in or not check_out:
            flash("Enter valid booking details and dates.", "error")
        elif date_error:
            flash(date_error, "error")
        elif check_in < date.today().isoformat():
            flash("Check-in cannot be in the past.", "error")
        elif check_in >= check_out:
            flash("Check-out must be after check-in.", "error")
        elif not guest_error:
            conn = cur = None
            try:
                conn = connection()
                cur = conn.cursor()
                cur.execute("""SELECT rm.room_id
                    FROM Room rm
                    WHERE rm.type_id=%s AND rm.status <> 'Maintenance'
                      AND NOT EXISTS (
                        SELECT 1 FROM Reservation r
                        WHERE r.room_id=rm.room_id
                          AND r.status IN ('Booked','Checked-in')
                          AND r.check_in < %s AND r.check_out > %s
                      )
                    ORDER BY CAST(rm.room_no AS UNSIGNED), rm.room_id LIMIT 1 FOR UPDATE""",
                            (room_type_id, check_out, check_in))
                room = cur.fetchone()
                if not room:
                    conn.rollback()
                    flash("No room of that type is available for those dates.", "error")
                else:
                    room_id = room[0]
                    if new_guest:
                        guest_id = write_guest(cur, guest_values)
                    cur.callproc("book_room", (guest_id, room_id, check_in, check_out))
                    conn.commit()
                    flash("Reservation booked successfully.", "success")
                    return redirect(url_for("listing", key="reservations"))
            except Error as exc:
                if conn:
                    conn.rollback()
                app.logger.warning("Reservation booking failed (errno=%s)", exc.errno)
                if getattr(exc, "errno", None) == 1062:
                    flash("A guest with that phone number or email already exists.", "error")
                else:
                    flash("Booking failed. Check the dates, guest, and room availability.", "error")
            finally:
                if cur:
                    cur.close()
                if conn:
                    conn.close()
            return redirect(url_for("book"))
    guests = query("SELECT guest_id,name FROM guest_details_view ORDER BY name, guest_id")
    room_types = query("SELECT type_id, type_name, rent_per_day FROM RoomType ORDER BY rent_per_day")
    return render_template("reservation_form.html", guests=guests, room_types=room_types)


@app.route("/reports")
@safe_db
def reports():
    reports_list = [
        ("Booking details", """SELECT r.reservation_id,c.name,rm.room_no,h.hotel_name,
         rt.type_name,r.check_in,r.check_out,r.status FROM Reservation r
         INNER JOIN guest_details_view c ON c.guest_id=r.guest_id INNER JOIN Room rm ON rm.room_id=r.room_id
         INNER JOIN Hotel h ON h.hotel_id=rm.hotel_id INNER JOIN RoomType rt ON rt.type_id=rm.type_id
         ORDER BY r.check_in DESC LIMIT 50"""),
        ("LEFT JOIN - guests who never booked", """SELECT c.guest_id,c.name,c.city
         FROM guest_details_view c LEFT JOIN Reservation r ON r.guest_id=c.guest_id
         WHERE r.reservation_id IS NULL ORDER BY c.name LIMIT 50"""),
        ("RIGHT JOIN - rooms never booked", """SELECT rm.room_id,rm.room_no,h.hotel_name
         FROM Reservation r RIGHT JOIN Room rm ON rm.room_id=r.room_id
         JOIN Hotel h ON h.hotel_id=rm.hotel_id WHERE r.reservation_id IS NULL LIMIT 50"""),
        ("Aggregate + JOIN - payment per guest", """SELECT c.guest_id,c.name,SUM(p.amount) total_paid
         FROM guest_details_view c JOIN Reservation r ON r.guest_id=c.guest_id JOIN Payment p
         ON p.reservation_id=r.reservation_id GROUP BY c.guest_id,c.name
         ORDER BY total_paid DESC LIMIT 20"""),
        ("Aggregate - revenue by hotel", """SELECT h.hotel_name,SUM(p.amount) revenue
         FROM Hotel h JOIN Room rm ON rm.hotel_id=h.hotel_id JOIN Reservation r ON r.room_id=rm.room_id
         JOIN Payment p ON p.reservation_id=r.reservation_id GROUP BY h.hotel_id,h.hotel_name
         ORDER BY revenue DESC LIMIT 20"""),
        ("Aggregate - bookings by city/state", """SELECT c.city,c.state,COUNT(*) bookings
         FROM guest_details_view c JOIN Reservation r ON r.guest_id=c.guest_id
         GROUP BY c.city,c.state HAVING COUNT(*) > 1 ORDER BY bookings DESC LIMIT 50"""),
        ("Subquery - guests paying above average", """WITH guest_totals AS (
         SELECT c.guest_id,c.name,SUM(p.amount) total_paid
         FROM guest_details_view c JOIN Reservation r ON r.guest_id=c.guest_id JOIN Payment p
         ON p.reservation_id=r.reservation_id GROUP BY c.guest_id,c.name
         ) SELECT guest_id,name,total_paid FROM guest_totals
         WHERE total_paid > (SELECT AVG(total_paid) FROM guest_totals)
         ORDER BY total_paid DESC LIMIT 20"""),
        ("Self join - guests from the same city", """SELECT a.name guest_a,b.name guest_b,a.city
         FROM guest_details_view a JOIN guest_details_view b ON b.city=a.city AND b.state=a.state AND b.guest_id>a.guest_id
         ORDER BY a.city,a.name,b.name LIMIT 50"""),
    ]
    results = []
    for title, sql in reports_list:
        try:
            results.append((title, sql, query(sql)))
        except Error as exc:
            app.logger.warning("Report query failed: %s (errno=%s)", title, exc.errno)
            results.append((title, sql, [{"error": "This report is temporarily unavailable."}]))
    return render_template("reports.html", reports=results)


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
