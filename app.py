import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_connection, init_db
from common import save_image, delete_image, UPLOAD_DIR
from email_service import (
    booking_confirmation, booking_status, cancellation_requested, cancellation_decision,
    new_booking_manager, manager_cancellation_request, admin_event
)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "stayflow-monolith-session-secret")
app.config.update(
    SESSION_COOKIE_NAME="stayflow_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_PATH="/",
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
)
SECRET_KEY = os.environ.get("JWT_SECRET", "stayflow-development-secret-key-32bytes-long")
ROLE_ROUTES = {"admin": "/admin/dashboard", "manager": "/manager/dashboard", "guest": "/guest/dashboard"}

init_db()


def create_token(user):
    return jwt.encode({
        "user_id": user["id"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=2)
    }, SECRET_KEY, algorithm="HS256")


def role_required(role):
    def deco(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            if session.get("role") != role:
                flash("Please sign in with an authorized account.", "error")
                return redirect(url_for("login"))
            return func(*args, **kwargs)
        return wrapped
    return deco


def notify(conn, user_id, title, message):
    conn.execute(
        "INSERT INTO notifications(user_id,title,message) VALUES(?,?,?)",
        (user_id, title, message)
    )


def parse_dates():
    check_in = request.form.get("check_in", "")
    check_out = request.form.get("check_out", "")
    if not check_in or not check_out or check_out <= check_in:
        return None, None
    return check_in, check_out


# ---------------- Public hotel browsing ----------------

@app.route("/")
def home():
    conn = get_connection()
    hotels = conn.execute("""
        SELECT h.*,
               COUNT(r.id) AS room_count,
               SUM(CASE WHEN r.available=1 THEN 1 ELSE 0 END) AS available_count
        FROM hotels h
        LEFT JOIN rooms r ON r.hotel_id=h.id
        GROUP BY h.id
        ORDER BY h.rating DESC, h.name
    """).fetchall()
    conn.close()
    return render_template("home.html", hotels=hotels)


@app.route("/hotel/<int:hotel_id>")
def hotel_detail(hotel_id):
    conn = get_connection()
    hotel = conn.execute("""
        SELECT h.*, u.username AS manager_name
        FROM hotels h
        LEFT JOIN users u ON u.id=h.manager_id
        WHERE h.id=?
    """, (hotel_id,)).fetchone()

    if not hotel:
        conn.close()
        return "Hotel not found", 404

    rooms = conn.execute("""
        SELECT * FROM rooms
        WHERE hotel_id=?
        ORDER BY available DESC, price ASC, room_number
    """, (hotel_id,)).fetchall()

    stats = conn.execute("""
        SELECT COUNT(*) AS total_rooms,
               COALESCE(SUM(CASE WHEN available=1 THEN 1 ELSE 0 END),0) AS available_rooms
        FROM rooms WHERE hotel_id=?
    """, (hotel_id,)).fetchone()

    conn.close()
    return render_template("hotel_detail.html", hotel=hotel, rooms=rooms, stats=stats)


# IMPORTANT FIX:
# Hotel images must be publicly readable on the landing page before login.
@app.route("/media/<path:filename>")
def public_media(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/<role>/media/<path:filename>")
def legacy_media(role, filename):
    if role not in {"admin", "manager", "guest"}:
        return redirect(url_for("login"))
    return send_from_directory(UPLOAD_DIR, filename)


# ---------------- Authentication ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET" and session.get("role") in ROLE_ROUTES:
        return redirect(ROLE_ROUTES[session["role"]])

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_connection()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

        if user and user["role"] in ROLE_ROUTES and check_password_hash(user["password"], password):
            session.clear()
            session.update(
                user_id=user["id"],
                username=user["username"],
                role=user["role"],
                jwt=create_token(user)
            )
            return redirect(ROLE_ROUTES[user["role"]])

        error = "We couldn't verify those credentials. Please try again."

    return render_template("login.html", error=error)


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/session")
def current_session():
    if not session.get("user_id"):
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user_id": session["user_id"],
        "username": session["username"],
        "role": session["role"]
    }


# ---------------- Admin ----------------

@app.route("/admin")
def admin_root():
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    conn = get_connection()
    hotels = conn.execute("""
        SELECT h.*,u.username manager_name,
        (SELECT COUNT(*) FROM rooms r WHERE r.hotel_id=h.id) room_count,
        (SELECT COUNT(*) FROM rooms r WHERE r.hotel_id=h.id AND r.available=1) available_count,
        (SELECT COUNT(*) FROM bookings b WHERE b.hotel_id=h.id) booking_count
        FROM hotels h LEFT JOIN users u ON u.id=h.manager_id
        ORDER BY h.id DESC
    """).fetchall()
    managers = conn.execute("SELECT id,username FROM users WHERE role='manager' ORDER BY username").fetchall()
    users = conn.execute("SELECT id,username,role,email FROM users ORDER BY id DESC").fetchall()
    bookings = conn.execute("""
        SELECT b.*,u.username guest_name,u.email guest_email,h.name hotel_name,r.room_number,h.manager_id
        FROM bookings b
        JOIN users u ON u.id=b.guest_id
        JOIN hotels h ON h.id=b.hotel_id
        JOIN rooms r ON r.id=b.room_id
        ORDER BY b.id DESC
    """).fetchall()
    requests = conn.execute("""
        SELECT cr.*,b.check_in,b.check_out,u.username guest_name,h.name hotel_name
        FROM cancellation_requests cr
        JOIN bookings b ON b.id=cr.booking_id
        JOIN users u ON u.id=cr.guest_id
        JOIN hotels h ON h.id=cr.hotel_id
        ORDER BY cr.id DESC
    """).fetchall()
    stats = {
        "hotels": conn.execute("SELECT COUNT(*) n FROM hotels").fetchone()["n"],
        "rooms": conn.execute("SELECT COUNT(*) n FROM rooms").fetchone()["n"],
        "users": conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
        "bookings": conn.execute("SELECT COUNT(*) n FROM bookings").fetchone()["n"],
        "pending": conn.execute("SELECT COUNT(*) n FROM cancellation_requests WHERE status='Pending'").fetchone()["n"],
    }
    conn.close()
    return render_template("admin_dashboard.html", hotels=hotels, managers=managers,
                           users=users, bookings=bookings, requests=requests, stats=stats)


@app.route("/admin/hotel/add", methods=["POST"])
@role_required("admin")
def add_hotel():
    image = None
    try:
        image = save_image(request.files.get("image"))
        conn = get_connection()
        conn.execute(
            "INSERT INTO hotels(name,location,description,image,rating) VALUES(?,?,?,?,?)",
            (request.form["name"].strip(), request.form["location"].strip(),
             request.form.get("description", "").strip(),
             image, float(request.form.get("rating") or 4.5))
        )
        conn.commit()
        conn.close()
        flash("Hotel created successfully.", "success")
    except Exception as exc:
        delete_image(image)
        flash(str(exc), "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/hotel/<int:id>/update", methods=["POST"])
@role_required("admin")
def update_hotel(id):
    conn = get_connection()
    old = conn.execute("SELECT image FROM hotels WHERE id=?", (id,)).fetchone()
    if not old:
        conn.close()
        flash("Hotel not found.", "error")
        return redirect(url_for("admin_dashboard"))

    new_image = None
    try:
        if request.files.get("image") and request.files["image"].filename:
            new_image = save_image(request.files["image"])

        conn.execute("""
            UPDATE hotels SET name=?,location=?,description=?,image=?,rating=?
            WHERE id=?
        """, (
            request.form["name"].strip(),
            request.form["location"].strip(),
            request.form.get("description", "").strip(),
            new_image or old["image"],
            float(request.form.get("rating") or 4.5),
            id
        ))
        conn.commit()
        conn.close()
        if new_image:
            delete_image(old["image"])
        flash("Hotel updated successfully.", "success")
    except Exception as exc:
        conn.close()
        delete_image(new_image)
        flash(str(exc), "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/hotel/<int:id>/assign", methods=["POST"])
@role_required("admin")
def assign_manager(id):
    manager_id = request.form.get("manager_id") or None
    conn = get_connection()
    hotel = conn.execute("SELECT name FROM hotels WHERE id=?", (id,)).fetchone()
    manager = conn.execute(
        "SELECT username FROM users WHERE id=? AND role='manager'", (manager_id,)
    ).fetchone() if manager_id else None

    conn.execute("UPDATE hotels SET manager_id=? WHERE id=?", (manager_id, id))
    if manager and hotel:
        notify(conn, int(manager_id), "Hotel assigned", f"You are now responsible for {hotel['name']}.")

    conn.commit()
    conn.close()
    flash("Manager assignment updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/hotel/<int:id>/delete", methods=["POST"])
@role_required("admin")
def delete_hotel(id):
    conn = get_connection()
    hotel = conn.execute("SELECT image FROM hotels WHERE id=?", (id,)).fetchone()
    conn.execute("DELETE FROM hotels WHERE id=?", (id,))
    conn.commit()
    conn.close()
    if hotel:
        delete_image(hotel["image"])
    flash("Hotel deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/user/add", methods=["POST"])
@role_required("admin")
def add_user():
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users(username,password,role,email) VALUES(?,?,?,?)",
            (
                request.form["username"].strip(),
                generate_password_hash(request.form["password"]),
                request.form["role"],
                request.form.get("email", "").strip() or None
            )
        )
        conn.commit()
        flash("User created.", "success")
    except Exception:
        flash("Username already exists.", "error")
    finally:
        conn.close()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/user/<int:id>/update", methods=["POST"])
@role_required("admin")
def update_user(id):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        email = request.form.get("email", "").strip() or None
        if request.form.get("password"):
            conn.execute("""
                UPDATE users SET username=?,password=?,role=?,email=? WHERE id=?
            """, (
                request.form["username"].strip(),
                generate_password_hash(request.form["password"]),
                request.form["role"],
                email,
                id
            ))
        else:
            conn.execute("UPDATE users SET username=?,role=?,email=? WHERE id=?",
                         (request.form["username"].strip(), request.form["role"], email, id))
        conn.commit()
        flash("User updated.", "success")
    except Exception:
        flash("Could not update user. Username may already exist.", "error")
    finally:
        conn.close()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/user/<int:id>/delete", methods=["POST"])
@role_required("admin")
def delete_user(id):
    if id == session["user_id"]:
        flash("You cannot delete your current account.", "error")
        return redirect(url_for("admin_dashboard"))

    conn = get_connection()
    conn.execute("UPDATE hotels SET manager_id=NULL WHERE manager_id=?", (id,))
    conn.execute("DELETE FROM users WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash("User deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/booking/<int:id>/update", methods=["POST"])
@role_required("admin")
def admin_update_booking(id):
    status = request.form["status"]
    conn = get_connection()
    booking = conn.execute("""
        SELECT b.*,u.username guest_name,u.email guest_email
        FROM bookings b JOIN users u ON u.id=b.guest_id WHERE b.id=?
    """, (id,)).fetchone()

    if not booking:
        conn.close()
        flash("Booking not found.", "error")
        return redirect(url_for("admin_dashboard"))

    conn.execute(
        "UPDATE bookings SET check_in=?,check_out=?,status=? WHERE id=?",
        (request.form["check_in"], request.form["check_out"], status, id)
    )
    conn.execute(
        "UPDATE rooms SET available=? WHERE id=?",
        (0 if status in ("Booked", "Checked-in") else 1, booking["room_id"])
    )
    notify(conn, booking["guest_id"], "Booking updated", f"Booking #{id} is now {status}.")
    admins = conn.execute("SELECT username,email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''").fetchall()
    conn.commit()
    conn.close()

    booking_status(booking["guest_email"], booking["guest_name"], id, status)
    for admin in admins:
        admin_event(admin["email"], admin["username"], "Booking status changed", f"Booking #{id} was changed to {status} by an administrator.", id)
    flash("Booking updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/booking/<int:id>/delete", methods=["POST"])
@role_required("admin")
def admin_delete_booking(id):
    conn = get_connection()
    b = conn.execute("SELECT * FROM bookings WHERE id=?", (id,)).fetchone()
    if b:
        conn.execute("DELETE FROM bookings WHERE id=?", (id,))
        conn.execute("UPDATE rooms SET available=1 WHERE id=?", (b["room_id"],))
    conn.commit()
    conn.close()
    flash("Booking deleted.", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------- Manager ----------------

@app.route("/manager")
def manager_root():
    return redirect(url_for("manager_dashboard"))


@app.route("/manager/dashboard")
@role_required("manager")
def manager_dashboard():
    conn = get_connection()
    hotels = conn.execute("SELECT * FROM hotels WHERE manager_id=? ORDER BY name",
                           (session["user_id"],)).fetchall()
    rooms = conn.execute("""
        SELECT r.*,h.name hotel_name FROM rooms r JOIN hotels h ON h.id=r.hotel_id
        WHERE h.manager_id=? ORDER BY r.id DESC
    """, (session["user_id"],)).fetchall()
    bookings = conn.execute("""
        SELECT b.*,u.username guest_name,u.email guest_email,h.name hotel_name,
               r.room_number,r.room_type
        FROM bookings b
        JOIN users u ON u.id=b.guest_id
        JOIN hotels h ON h.id=b.hotel_id
        JOIN rooms r ON r.id=b.room_id
        WHERE h.manager_id=? ORDER BY b.id DESC
    """, (session["user_id"],)).fetchall()
    requests = conn.execute("""
        SELECT cr.*,b.check_in,b.check_out,u.username guest_name,h.name hotel_name,
               r.room_number
        FROM cancellation_requests cr
        JOIN bookings b ON b.id=cr.booking_id
        JOIN users u ON u.id=cr.guest_id
        JOIN hotels h ON h.id=cr.hotel_id
        JOIN rooms r ON r.id=b.room_id
        WHERE h.manager_id=?
        ORDER BY CASE WHEN cr.status='Pending' THEN 0 ELSE 1 END, cr.id DESC
    """, (session["user_id"],)).fetchall()
    unread = conn.execute(
        "SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0",
        (session["user_id"],)
    ).fetchone()["n"]

    stats = {
        "hotels": len(hotels),
        "rooms": len(rooms),
        "available": sum(r["available"] for r in rooms),
        "bookings": len(bookings),
        "pending": sum(1 for x in requests if x["status"] == "Pending")
    }
    conn.close()

    return render_template("manager_dashboard.html", hotels=hotels, rooms=rooms,
                           bookings=bookings, requests=requests, stats=stats, unread=unread)


@app.route("/manager/room/add", methods=["POST"])
@role_required("manager")
def add_room():
    image = None
    conn = get_connection()
    try:
        hotel = conn.execute(
            "SELECT id FROM hotels WHERE id=? AND manager_id=?",
            (request.form["hotel_id"], session["user_id"])
        ).fetchone()
        if not hotel:
            raise ValueError("You can only add rooms to hotels assigned to you.")

        image = save_image(request.files.get("image"))
        conn.execute("""
            INSERT INTO rooms(hotel_id,room_number,room_type,price,available,image,amenities)
            VALUES(?,?,?,?,?,?,?)
        """, (
            hotel["id"], request.form["room_number"].strip(),
            request.form["room_type"].strip(), float(request.form["price"]),
            1, image, request.form.get("amenities", "").strip()
        ))
        conn.commit()
        flash("Room created.", "success")
    except Exception as exc:
        delete_image(image)
        flash(str(exc), "error")
    finally:
        conn.close()
    return redirect(url_for("manager_dashboard"))


@app.route("/manager/room/<int:id>/update", methods=["POST"])
@role_required("manager")
def update_room(id):
    conn = get_connection()
    old = conn.execute("""
        SELECT r.*,h.manager_id FROM rooms r JOIN hotels h ON h.id=r.hotel_id WHERE r.id=?
    """, (id,)).fetchone()

    if not old or old["manager_id"] != session["user_id"]:
        conn.close()
        flash("Room not found.", "error")
        return redirect(url_for("manager_dashboard"))

    new_image = None
    try:
        hotel = conn.execute(
            "SELECT id FROM hotels WHERE id=? AND manager_id=?",
            (request.form["hotel_id"], session["user_id"])
        ).fetchone()
        if not hotel:
            raise ValueError("Invalid hotel assignment.")

        if request.files.get("image") and request.files["image"].filename:
            new_image = save_image(request.files["image"])

        conn.execute("""
            UPDATE rooms SET hotel_id=?,room_number=?,room_type=?,price=?,
            available=?,image=?,amenities=? WHERE id=?
        """, (
            hotel["id"], request.form["room_number"].strip(),
            request.form["room_type"].strip(), float(request.form["price"]),
            int(request.form["available"]), new_image or old["image"],
            request.form.get("amenities", "").strip(), id
        ))
        conn.commit()
        flash("Room updated.", "success")
        if new_image:
            delete_image(old["image"])
    except Exception as exc:
        delete_image(new_image)
        flash(str(exc), "error")
    finally:
        conn.close()
    return redirect(url_for("manager_dashboard"))


@app.route("/manager/room/<int:id>/delete", methods=["POST"])
@role_required("manager")
def delete_room(id):
    conn = get_connection()
    room = conn.execute("""
        SELECT r.image FROM rooms r JOIN hotels h ON h.id=r.hotel_id
        WHERE r.id=? AND h.manager_id=?
    """, (id, session["user_id"])).fetchone()

    if room:
        conn.execute("DELETE FROM rooms WHERE id=?", (id,))
        conn.commit()
        delete_image(room["image"])
        flash("Room deleted.", "success")
    else:
        flash("Room not found.", "error")

    conn.close()
    return redirect(url_for("manager_dashboard"))


@app.route("/manager/booking/<int:id>/status", methods=["POST"])
@role_required("manager")
def manager_booking_status(id):
    status = request.form["status"]
    conn = get_connection()
    b = conn.execute("""
        SELECT b.*,u.username guest_name,u.email guest_email
        FROM bookings b
        JOIN users u ON u.id=b.guest_id
        JOIN hotels h ON h.id=b.hotel_id
        WHERE b.id=? AND h.manager_id=?
    """, (id, session["user_id"])).fetchone()

    if b:
        conn.execute("UPDATE bookings SET status=? WHERE id=?", (status, id))
        conn.execute(
            "UPDATE rooms SET available=? WHERE id=?",
            (0 if status in ("Booked", "Checked-in") else 1, b["room_id"])
        )
        notify(conn, b["guest_id"], "Booking status changed", f"Booking #{id} is now {status}.")
        admins = conn.execute("SELECT username,email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''").fetchall()
        conn.commit()
        booking_status(b["guest_email"], b["guest_name"], id, status)
        for admin in admins:
            admin_event(admin["email"], admin["username"], "Booking status changed", f"Booking #{id} at hotel #{b['hotel_id']} was changed to {status} by manager {session.get('username','')}.", id)
        flash("Booking status updated.", "success")
    else:
        flash("Booking not found.", "error")

    conn.close()
    return redirect(url_for("manager_dashboard"))


@app.route("/manager/cancellation/<int:id>/review", methods=["POST"])
@role_required("manager")
def review_cancellation(id):
    decision = request.form["decision"]
    note = request.form.get("manager_note", "").strip()
    conn = get_connection()

    cr = conn.execute("""
        SELECT cr.*,b.room_id,b.guest_id,u.username guest_name,u.email guest_email
        FROM cancellation_requests cr
        JOIN bookings b ON b.id=cr.booking_id
        JOIN users u ON u.id=cr.guest_id
        JOIN hotels h ON h.id=cr.hotel_id
        WHERE cr.id=? AND h.manager_id=?
    """, (id, session["user_id"])).fetchone()

    if not cr or cr["status"] != "Pending":
        conn.close()
        flash("Cancellation request is no longer pending.", "error")
        return redirect(url_for("manager_dashboard"))

    if decision == "approve":
        conn.execute("""
            UPDATE cancellation_requests
            SET status='Approved',manager_note=?,reviewed_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (note, id))
        conn.execute("UPDATE bookings SET status='Cancelled' WHERE id=?", (cr["booking_id"],))
        conn.execute("UPDATE rooms SET available=1 WHERE id=?", (cr["room_id"],))
        notify(conn, cr["guest_id"], "Cancellation approved",
               f"Your cancellation request for booking #{cr['booking_id']} was approved.")
        result = "Approved"
    else:
        conn.execute("""
            UPDATE cancellation_requests
            SET status='Rejected',manager_note=?,reviewed_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (note, id))
        notify(conn, cr["guest_id"], "Cancellation rejected",
               f"Your cancellation request for booking #{cr['booking_id']} was rejected.")
        result = "Rejected"

    conn.commit()
    conn.close()

    cancellation_decision(cr["guest_email"], cr["guest_name"], cr["booking_id"], result, note)
    conn2 = get_connection()
    admins = conn2.execute("SELECT username,email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''").fetchall()
    conn2.close()
    for admin in admins:
        admin_event(admin["email"], admin["username"], f"Cancellation {result.lower()}", f"Cancellation request for booking #{cr['booking_id']} was {result.lower()} by manager {session.get('username','')}.", cr["booking_id"])
    flash(f"Cancellation {result.lower()}.", "success")
    return redirect(url_for("manager_dashboard"))


@app.route("/manager/notifications/read", methods=["POST"])
@role_required("manager")
def manager_notifications_read():
    conn = get_connection()
    conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    conn.commit()
    conn.close()
    flash("Notifications marked as read.", "success")
    return redirect(url_for("manager_dashboard"))


# ---------------- Guest ----------------

@app.route("/guest")
def guest_root():
    return redirect(url_for("guest_dashboard"))


@app.route("/guest/dashboard")
@role_required("guest")
def guest_dashboard():
    q=request.args.get("q","").strip(); location=request.args.get("location","").strip(); conn=get_connection()
    sql="""SELECT h.*,COUNT(r.id) room_count,COALESCE(SUM(CASE WHEN r.available=1 THEN 1 ELSE 0 END),0) available_count FROM hotels h LEFT JOIN rooms r ON r.hotel_id=h.id WHERE 1=1"""; params=[]
    if q:
        sql += " AND (h.name LIKE ? OR h.location LIKE ? OR h.description LIKE ?)"; params += [f"%{q}%"]*3
    if location:
        sql += " AND h.location LIKE ?"; params.append(f"%{location}%")
    sql += " GROUP BY h.id ORDER BY h.rating DESC,h.name"; hotels=conn.execute(sql,params).fetchall()
    bookings=conn.execute("""SELECT b.*,r.room_number,r.room_type,r.image room_image,h.name hotel_name,h.location,cr.id request_id,cr.status request_status,cr.reason request_reason,cr.manager_note FROM bookings b JOIN rooms r ON r.id=b.room_id JOIN hotels h ON h.id=b.hotel_id LEFT JOIN cancellation_requests cr ON cr.booking_id=b.id AND cr.id=(SELECT MAX(id) FROM cancellation_requests x WHERE x.booking_id=b.id) WHERE b.guest_id=? ORDER BY b.id DESC""",(session["user_id"],)).fetchall()
    notifications=conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 8",(session["user_id"],)).fetchall()
    unread=conn.execute("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0",(session["user_id"],)).fetchone()["n"]
    conn.close(); return render_template("guest_dashboard.html",hotels=hotels,bookings=bookings,q=q,location=location,notifications=notifications,unread=unread)


@app.route("/guest/book/<int:room_id>", methods=["POST"])
@role_required("guest")
def book(room_id):
    check_in, check_out = parse_dates()
    if not check_in:
        flash("Please choose valid check-in and check-out dates.", "error")
        return redirect(url_for("guest_dashboard"))

    conn = get_connection()
    room = conn.execute(
        "SELECT * FROM rooms WHERE id=? AND available=1", (room_id,)
    ).fetchone()

    if not room:
        conn.close()
        flash("Room is no longer available.", "error")
        return redirect(url_for("guest_dashboard"))

    conn.execute("""
        INSERT INTO bookings(guest_id,room_id,hotel_id,check_in,check_out,status)
        VALUES(?,?,?,?,?,?)
    """, (
        session["user_id"], room_id, room["hotel_id"],
        check_in, check_out, "Booked"
    ))
    booking_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("UPDATE rooms SET available=0 WHERE id=?", (room_id,))

    hotel = conn.execute(
        "SELECT manager_id,name FROM hotels WHERE id=?", (room["hotel_id"],)
    ).fetchone()
    guest = conn.execute(
        "SELECT username,email FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()

    manager = conn.execute("SELECT username,email FROM users WHERE id=?", (hotel["manager_id"],)).fetchone() if hotel and hotel["manager_id"] else None
    admins = conn.execute("SELECT username,email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''").fetchall()
    if hotel and hotel["manager_id"]:
        notify(conn, hotel["manager_id"], "New booking", f"A new booking was created at {hotel['name']}.")

    conn.commit()
    conn.close()

    booking_confirmation(guest["email"], guest["username"], booking_id, hotel["name"], room["room_number"], check_in, check_out)
    if manager and manager["email"]:
        new_booking_manager(manager["email"], manager["username"], booking_id, guest["username"], hotel["name"], room["room_number"], check_in, check_out)
    for admin in admins:
        admin_event(admin["email"], admin["username"], "New booking created", f"Booking #{booking_id} was created by {guest['username']} at {hotel['name']}.", booking_id)

    flash("Your stay is confirmed. A confirmation email was sent if SMTP is configured.", "success")
    return redirect(url_for("guest_dashboard"))


@app.route("/guest/booking/<int:id>/update", methods=["POST"])
@role_required("guest")
def guest_update_booking(id):
    check_in, check_out = parse_dates()
    if not check_in:
        flash("Please choose valid dates.", "error")
        return redirect(url_for("guest_dashboard"))

    conn = get_connection()
    b = conn.execute("""
        SELECT b.*,u.username guest_name,u.email guest_email,h.name hotel_name,h.manager_id
        FROM bookings b JOIN users u ON u.id=b.guest_id JOIN hotels h ON h.id=b.hotel_id
        WHERE b.id=? AND b.guest_id=? AND b.status='Booked'
    """, (id, session["user_id"])).fetchone()

    if b:
        conn.execute(
            "UPDATE bookings SET check_in=?,check_out=? WHERE id=?",
            (check_in, check_out, id)
        )
        manager = conn.execute("SELECT username,email FROM users WHERE id=?", (b["manager_id"],)).fetchone() if b["manager_id"] else None
        admins = conn.execute("SELECT username,email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''").fetchall()
        conn.commit()
        booking_status(b["guest_email"], b["guest_name"], id, "Booked — dates updated", b["hotel_name"], None)
        if manager and manager["email"]:
            admin_event(manager["email"], manager["username"], "Guest booking dates updated", f"Guest {b['guest_name']} updated dates for booking #{id} at {b['hotel_name']}.", id)
        for admin in admins:
            admin_event(admin["email"], admin["username"], "Booking dates updated", f"Guest {b['guest_name']} updated dates for booking #{id} at {b['hotel_name']}.", id)
        flash("Booking dates updated.", "success")
    else:
        flash("Only active bookings can be updated.", "error")

    conn.close()
    return redirect(url_for("guest_dashboard"))


@app.route("/guest/booking/<int:id>/cancel-request", methods=["POST"])
@role_required("guest")
def cancellation_request(id):
    reason = request.form.get("reason", "").strip() or "Guest requested cancellation"
    conn = get_connection()

    b = conn.execute("""
        SELECT b.*,u.username guest_name,u.email guest_email,h.name hotel_name
        FROM bookings b
        JOIN users u ON u.id=b.guest_id
        JOIN hotels h ON h.id=b.hotel_id
        WHERE b.id=? AND b.guest_id=?
    """, (id, session["user_id"])).fetchone()

    pending = conn.execute(
        "SELECT id FROM cancellation_requests WHERE booking_id=? AND status='Pending'",
        (id,)
    ).fetchone()

    if not b or b["status"] not in ("Booked", "Checked-in"):
        flash("This booking cannot be cancelled.", "error")
    elif pending:
        flash("A cancellation request is already pending.", "error")
    else:
        conn.execute("""
            INSERT INTO cancellation_requests(booking_id,guest_id,hotel_id,reason)
            VALUES(?,?,?,?)
        """, (id, session["user_id"], b["hotel_id"], reason))

        manager = conn.execute("SELECT manager_id,name FROM hotels WHERE id=?", (b["hotel_id"],)).fetchone()
        manager_user = conn.execute("SELECT username,email FROM users WHERE id=?", (manager["manager_id"],)).fetchone() if manager and manager["manager_id"] else None
        admins = conn.execute("SELECT username,email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''").fetchall()

        if manager and manager["manager_id"]:
            notify(conn, manager["manager_id"], "Cancellation request",
                   f"A guest requested cancellation for booking #{id} at {manager['name']}.")

        conn.commit()
        cancellation_requested(b["guest_email"], b["guest_name"], id, b["hotel_name"], reason)
        if manager_user and manager_user["email"]:
            manager_cancellation_request(manager_user["email"], manager_user["username"], id, b["guest_name"], b["hotel_name"], reason)
        for admin in admins:
            admin_event(admin["email"], admin["username"], "Cancellation request received", f"Booking #{id} cancellation was requested by {b['guest_name']} at {b['hotel_name']}.", id)
        flash("Cancellation request sent to the hotel manager.", "success")

    conn.close()
    return redirect(url_for("guest_dashboard"))


@app.route("/guest/notifications/read", methods=["POST"])
@role_required("guest")
def guest_notifications_read():
    conn = get_connection()
    conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    conn.commit()
    conn.close()
    return redirect(url_for("guest_dashboard"))


@app.route("/guest/booking/<int:id>/delete", methods=["POST"])
@role_required("guest")
def delete_booking(id):
    conn = get_connection()
    b = conn.execute(
        "SELECT * FROM bookings WHERE id=? AND guest_id=?",
        (id, session["user_id"])
    ).fetchone()

    if b and b["status"] == "Cancelled":
        conn.execute("DELETE FROM bookings WHERE id=?", (id,))
        conn.commit()
        flash("Booking record removed.", "success")
    else:
        flash("Only cancelled bookings can be removed from your history.", "error")

    conn.close()
    return redirect(url_for("guest_dashboard"))


@app.route("/health")
def health():
    return {"application": "StayFlow", "status": "ok", "architecture": "monolith"}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=3500, debug=True, use_reloader=False)