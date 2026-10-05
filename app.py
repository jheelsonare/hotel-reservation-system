"""Indian Hotel Management System - Flask/MySQL application."""
import os
import secrets
import hmac
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from urllib.parse import urlencode

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from mysql.connector import Error

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret")
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
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
    return mysql.connector.connect(**DB_CONFIG)


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
            app.logger.exception("Database operation failed")
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
        counts["guests"] = query("SELECT COUNT(*) n FROM Guest", one=True)["n"]
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
            FROM Reservation r JOIN Guest c ON c.guest_id=r.guest_id
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
    search = request.args.get("q", "").strip()
    sort = request.args.get("sort", pk)
    if sort not in fields + [pk]:
        sort = pk
    where, params = "", []
    from_sql = f"`{table}`"
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
    record = query(f"SELECT * FROM `{table}` WHERE `{pk}`=%s", (item_id,), one=True) if item_id else {}
    if item_id and not record:
        flash(f"{table} not found.", "error")
        return redirect(url_for("listing", key=key))
    if request.method == "POST":
        if not valid_csrf():
            flash("Your form expired. Please try again.", "error")
            return redirect(request.url)
        values = [request.form.get(field, "").strip() or None for field in fields]
        error = validate(key, values)
        if error:
            flash(error, "error")
        else:
            if item_id:
                execute(f"UPDATE `{table}` SET " + ", ".join(f"`{f}`=%s" for f in fields) +
                        f" WHERE `{pk}`=%s", values + [item_id])
            else:
                execute(f"INSERT INTO `{table}` (" + ",".join(f"`{f}`" for f in fields) +
                        ") VALUES (" + ",".join(["%s"] * len(fields)) + ")", values)
            flash(f"{table} saved.", "success")
            return redirect(url_for("listing", key=key))
    foreign_options = {}
    if key == "rooms":
        foreign_options[("rooms", "hotel_id")] = query("SELECT hotel_id id, hotel_name label FROM Hotel ORDER BY hotel_name")
        foreign_options[("rooms", "type_id")] = query("SELECT type_id id, type_name label FROM RoomType ORDER BY type_name")
    elif key == "reservations":
        foreign_options[("reservations", "guest_id")] = query("SELECT guest_id id, CONCAT(name, ' (#', guest_id, ')') label FROM Guest ORDER BY name, guest_id")
        foreign_options[("reservations", "room_id")] = query("SELECT room_id id, CONCAT(room_no, ' (#', room_id, ')') label FROM Room ORDER BY CAST(room_no AS UNSIGNED), room_id")
    elif key == "payments":
        foreign_options[("payments", "reservation_id")] = query("SELECT reservation_id id, CONCAT('#', reservation_id, ' ', check_in, ' to ', check_out) label FROM Reservation ORDER BY check_in DESC, reservation_id DESC")
    return render_template("form.html", key=key, table=table, pk=pk, fields=fields,
                           record=record, item_id=item_id,
                           field_choices=FIELD_CHOICES, foreign_options=foreign_options)


def validate(key, values):
    import re
    if key == "guests" and (not values[0] or not values[1]):
        return "Guest name and phone are required."
    if key == "guests" and not re.fullmatch(r"[6-9]\d{9}", str(values[1])):
        return "Phone must be a 10-digit Indian mobile number starting with 6-9."
    if key == "guests" and values[2] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(values[2])):
        return "Enter a valid email address."
    if key == "reservations":
        if not values[0] or not values[1] or not values[2] or not values[3]:
            return "Guest, room, check-in and check-out are required."
        if str(values[2]) >= str(values[3]):
            return "Check-out must be after check-in."
        if values[4] in ("Booked", "Checked-in") and str(values[2]) < date.today().isoformat():
            return "Active reservations cannot start in the past."
        if values[4] not in FIELD_CHOICES[("reservations", "status")]:
            return "Choose a valid reservation status."
    if key == "rooms" and values[4] not in FIELD_CHOICES[("rooms", "status")]:
        return "Choose Available or Maintenance for room status."
    if key == "payments" and values[3] not in FIELD_CHOICES[("payments", "mode")]:
        return "Choose a valid payment mode."
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
                        cur.execute(
                            """INSERT INTO Guest
                            (name, phone, email, city, state, id_proof_type, id_proof_no)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                            guest_values,
                        )
                        guest_id = cur.lastrowid
                    cur.callproc("book_room", (guest_id, room_id, check_in, check_out))
                    conn.commit()
                    flash("Reservation booked successfully.", "success")
                    return redirect(url_for("listing", key="reservations"))
            except Error as exc:
                if conn:
                    conn.rollback()
                app.logger.exception("Reservation booking failed")
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
    guests = query("SELECT guest_id,name FROM Guest ORDER BY name, guest_id")
    room_types = query("SELECT type_id, type_name, rent_per_day FROM RoomType ORDER BY rent_per_day")
    return render_template("reservation_form.html", guests=guests, room_types=room_types)


@app.route("/reports")
@safe_db
def reports():
    reports_list = [
        ("Booking details", """SELECT r.reservation_id,c.name,rm.room_no,h.hotel_name,
         rt.type_name,r.check_in,r.check_out,r.status FROM Reservation r
         INNER JOIN Guest c ON c.guest_id=r.guest_id INNER JOIN Room rm ON rm.room_id=r.room_id
         INNER JOIN Hotel h ON h.hotel_id=rm.hotel_id INNER JOIN RoomType rt ON rt.type_id=rm.type_id
         ORDER BY r.check_in DESC LIMIT 50"""),
        ("LEFT JOIN - guests who never booked", """SELECT c.guest_id,c.name,c.city
         FROM Guest c LEFT JOIN Reservation r ON r.guest_id=c.guest_id
         WHERE r.reservation_id IS NULL ORDER BY c.name LIMIT 50"""),
        ("RIGHT JOIN - rooms never booked", """SELECT rm.room_id,rm.room_no,h.hotel_name
         FROM Reservation r RIGHT JOIN Room rm ON rm.room_id=r.room_id
         JOIN Hotel h ON h.hotel_id=rm.hotel_id WHERE r.reservation_id IS NULL LIMIT 50"""),
        ("Aggregate + JOIN - payment per guest", """SELECT c.guest_id,c.name,SUM(p.amount) total_paid
         FROM Guest c JOIN Reservation r ON r.guest_id=c.guest_id JOIN Payment p
         ON p.reservation_id=r.reservation_id GROUP BY c.guest_id,c.name
         ORDER BY total_paid DESC LIMIT 20"""),
        ("Aggregate - revenue by hotel", """SELECT h.hotel_name,SUM(p.amount) revenue
         FROM Hotel h JOIN Room rm ON rm.hotel_id=h.hotel_id JOIN Reservation r ON r.room_id=rm.room_id
         JOIN Payment p ON p.reservation_id=r.reservation_id GROUP BY h.hotel_id,h.hotel_name
         ORDER BY revenue DESC LIMIT 20"""),
        ("Aggregate - bookings by city/state", """SELECT c.city,c.state,COUNT(*) bookings
         FROM Guest c JOIN Reservation r ON r.guest_id=c.guest_id
         GROUP BY c.city,c.state HAVING COUNT(*) > 1 ORDER BY bookings DESC LIMIT 50"""),
        ("Subquery - guests paying above average", """WITH guest_totals AS (
         SELECT c.guest_id,c.name,SUM(p.amount) total_paid
         FROM Guest c JOIN Reservation r ON r.guest_id=c.guest_id JOIN Payment p
         ON p.reservation_id=r.reservation_id GROUP BY c.guest_id,c.name
         ) SELECT guest_id,name,total_paid FROM guest_totals
         WHERE total_paid > (SELECT AVG(total_paid) FROM guest_totals)
         ORDER BY total_paid DESC LIMIT 20"""),
        ("Self join - guests from the same city", """SELECT a.name guest_a,b.name guest_b,a.city
         FROM Guest a JOIN Guest b ON b.city=a.city AND b.guest_id>a.guest_id
         ORDER BY a.city,a.name,b.name LIMIT 50"""),
    ]
    results = []
    for title, sql in reports_list:
        try:
            results.append((title, sql, query(sql)))
        except Error as exc:
            app.logger.exception("Report query failed: %s", title)
            results.append((title, sql, [{"error": "This report is temporarily unavailable."}]))
    return render_template("reports.html", reports=results)


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
