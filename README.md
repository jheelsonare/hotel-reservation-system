# Indian Hotel Management System

## Windows setup

1. Install MySQL 8 and create the database: `CREATE DATABASE hotel_db;`
2. Create the hotel tables:
   `mysql -u root -p hotel_db < schema.sql`
3. Load the Indian sample hotel, guests, rooms and reservations:
   `mysql -u root -p hotel_db < data.sql`
4. Add the booking procedure, availability view and indexes:
   `mysql -u root -p hotel_db < advanced.sql`
4. In PowerShell, create a virtual environment and install packages:
   `py -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt`
5. Configure credentials (defaults are root, empty password):
   `$env:DB_USER="root"; $env:DB_PASSWORD="your-password"`
   In PowerShell, set the password to the password configured for your local
   MySQL `root` account before starting the app. For example:
   `$env:DB_PASSWORD="your-actual-mysql-password"`
   You can also edit the `DB_CONFIG` block at the top of `app.py`; never commit
   a real password. Optional variables are `DB_HOST`, `DB_PORT`, `DB_NAME`,
   and `SECRET_KEY`.
6. Run: `python app.py`, then browse to http://127.0.0.1:5000.

The app is a single Indian hotel management application for hotel,
room and guest records. It supports searchable, sortable,
paginated CRUD pages, date-overlap validation, stored-procedure booking,
payments in INR and bounded SQL reports.

The requested advanced objects are in `advanced.sql` and must be run after
`schema.sql` and `data.sql`. The schema script recreates the tables, so use it
only when initializing or intentionally resetting a local database.
