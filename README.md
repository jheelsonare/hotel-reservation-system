# Hotel Reservation System

## Windows setup

1. Install MySQL 8 and create the database: `CREATE DATABASE hotel_db;`
2. Create the hotel tables:
   `mysql -u root -p hotel_db < schema.sql`
3. Load the Indian sample hotel, guests, rooms and reservations:
   `mysql -u root -p hotel_db < data.sql`
4. Add the booking procedure, date-aware availability view, overlap guards and indexes:
   `mysql -u root -p hotel_db < advanced.sql`
5. In PowerShell, create a virtual environment and install packages:
   `py -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt`
6. Copy `.env.example` to `.env` and configure credentials:
   `Copy-Item .env.example .env`
   The application loads `.env` automatically. Do not commit real credentials.
   `$env:DB_USER="root"; $env:DB_PASSWORD="your-password"`
   In PowerShell, set the password to the password configured for your local
   MySQL `root` account before starting the app. For example:
   `$env:DB_PASSWORD="your-actual-mysql-password"`
   You can also edit the `DB_CONFIG` block at the top of `app.py`; never commit
   a real password. Optional variables are `DB_HOST`, `DB_PORT`, `DB_NAME`,
   and `SECRET_KEY`.
7. Run: `python app.py`, then browse to http://127.0.0.1:5000.

The app is a single Indian hotel management application for hotel,
room and guest records. It supports searchable, sortable,
paginated CRUD pages, date-overlap validation, stored-procedure booking,
payments in INR and bounded SQL reports.

The requested advanced objects are in `advanced.sql` and must be run after
`schema.sql` and `data.sql`. `advanced.sql` is safe to run again: it replaces
the view, triggers and procedure and creates missing indexes only. The schema
script recreates the tables, so use it only when initializing or intentionally
resetting a local database.

Room status is physical state only (`Available` or `Maintenance`). Whether a
room is available is calculated for the requested dates, and active reservations
cannot overlap regardless of whether they are created through the UI, a
procedure, or direct SQL.
