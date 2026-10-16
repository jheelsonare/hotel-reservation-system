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


## BCNF design and guest locations

The seven base tables are Hotel, Location, Guest, RoomType, Room, Reservation,
and Payment. Guest references Location instead of repeating city/state text.
The same city name may occur in different states; the pair (city, state) is
unique. Forms still accept city and state and resolve the location automatically.
The guest_details_view joins them for display, search, and reports.
See [normalization.md](normalization.md) for candidate keys, dependencies,
BCNF assumptions, lossless reconstruction, and example SQL.

### Upgrade an existing six-table database (keep your data)

Stop the Flask app and back up your database before upgrading:

```powershell
mysqldump -u root -p --result-file=hotel_db_before_locations.sql hotel_db
```

Run these commands from Command Prompt, where input redirection is supported:

```bat
mysql -u root -p hotel_db < migrations/001_guest_locations.sql
mysql -u root -p hotel_db < advanced.sql
```

Then restart the updated app. The migration is one-time, not rerunnable;
MySQL DDL commits implicitly. It maps existing guests to locations and keeps
all guest IDs, reservations, and payments. If a statement fails, stop and
inspect the database before continuing or restore the backup. Do not use
schema.sql or reload data.sql for this upgrade. Fresh installations should
follow the original schema.sql -> data.sql -> advanced.sql setup sequence.

### Integration checks

Against a local MySQL test server:

```bat
python -m unittest discover -s tests -v
```

Set TEST_DB_HOST, TEST_DB_PORT, TEST_DB_USER, and TEST_DB_PASSWORD if needed.
Tests create randomly named temporary databases and never use the configured
application database. The test account needs CREATE/DROP DATABASE privileges.
