# StayFlow — Fixed Hotel Booking Monolith

This version fixes the hotel browsing flow and adds SMTP email integration.

## What was fixed

### 1. Hotels now display on the first page
- `/` shows hotels immediately.
- Hotel images are served by a public `/media/<filename>` route.
- The old image route required a logged-in session, which caused landing-page images to fail.
- Missing images have a clean visual fallback.
- Three demo hotels with local JPG images can be created with `seed_demo_data.py`.

### 2. Hotel → Rooms flow
Click any hotel on the landing page:

`/` → **Hotel card** → `/hotel/<hotel_id>`

The hotel detail page shows:
- Hotel image
- Hotel name/location/rating
- Total number of rooms
- Number of currently available rooms
- Every room in that hotel
- Room number
- Room type
- Amenities
- Price per night
- Availability

### 3. Guest browsing
After guest login, the guest dashboard still shows available rooms and now links each hotel name to its hotel-detail page.

### 4. Email integration
SMTP email is implemented in `email_service.py`.

Emails are sent asynchronously for:
- Booking confirmation
- Booking status changes
- Cancellation request acknowledgement
- Cancellation approval/rejection

If SMTP is not configured, the application continues working normally and only skips email delivery.

## Gmail App Password setup

Do **not** put your normal Gmail password into the application.

1. Enable 2-Step Verification on the Google account.
2. Create a Google App Password.
3. Copy the generated 16-character app password.
4. Copy `.env.example` to `.env`.
5. Fill these values:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-gmail-address@gmail.com
SMTP_APP_PASSWORD=your-16-character-google-app-password
MAIL_FROM=your-gmail-address@gmail.com
```

The project intentionally does not include a real app password.

> Important: this project reads environment variables. If you use a `.env` file, load it with your preferred environment loader or set the variables in the shell/IDE before starting Flask. For the simplest setup, use Windows PowerShell `setx`/environment settings or export variables in your terminal.

## Install

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

```bash
pip install -r requirements.txt
```

## Create demo hotels and rooms

Run this once for a new installation:

```bash
python seed_demo_data.py
```

It creates three hotels and nine rooms if the database has no hotels.

If you already have your own hotels, it does not add or modify them.

## Run

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Demo accounts

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `admin123` |
| Manager | `manager` | `manager123` |
| Guest | `guest` | `guest123` |

For email testing, edit the guest/manager user's email in the Admin dashboard.

## Important database behavior

The application automatically creates/migrates:
- users
- hotels
- rooms
- bookings
- cancellation_requests
- notifications

Existing databases are preserved. The new `users.email` field is added automatically.

## Recommended flow

1. Run `python seed_demo_data.py`.
2. Open `/` and verify hotel images.
3. Click a hotel and verify room count/rooms.
4. Login as guest.
5. Open a hotel from the guest dashboard.
6. Reserve a room.
7. Check the guest email for the booking confirmation.
8. Login as manager.
9. Update the booking status or review a cancellation.
10. Check the guest email again.

## Security note

For a real deployment:
- use strong random `SESSION_SECRET` and `JWT_SECRET`
- never commit `.env`
- never commit Gmail app passwords
- add CSRF protection
- use a production WSGI server
- use PostgreSQL/MySQL for production
- add proper booking date-overlap logic rather than a single `available` flag
- add audit logging and rate limiting

## Updated guest experience and email notifications

- Guest dashboard now starts with the same **hotel-first experience** as the public home page.
- Guests see hotel image, rating, location, total room count and available room count.
- Clicking **View hotel & rooms** opens that hotel's room inventory.
- Guests can reserve an available room directly from the hotel detail page.
- Booking emails use responsive, branded HTML hotel-style templates instead of plain-looking messages.
- Booking events use the email addresses stored in the `users.email` database column.
- New booking: guest receives confirmation; assigned manager and admin accounts with email addresses receive operational notifications.
- Guest date update: guest, assigned manager and admins are notified.
- Booking status update: guest and admins are notified.
- Cancellation request: guest receives acknowledgement; assigned manager and admins are notified.
- Cancellation decision: guest and admins are notified.
- Console output now clearly shows `[EMAIL] SUCCESS`, `[EMAIL] FAILED`, or `[EMAIL] Skipped`.

### Important
Never put a real Gmail App Password in source code or commit it to Git. Revoke any App Password that has been exposed and create a new one.