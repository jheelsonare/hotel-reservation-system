# Hotel Reservation System

A Flask/MySQL DBMS project with hotel, room, guest, reservation and payment CRUD,
room availability, SQL reports, joins, views, triggers, and transactions.

## Fresh Windows setup

1. Install MySQL 8.0.16 or newer (CHECK constraints require this version).
2. In **Command Prompt**, initialize the sample database. These commands recreate
   tables; use them only for a fresh installation or an intentional reset:

   ```bat
   mysql -u root -p < schema.sql
   mysql -u root -p hotel_db < data.sql
   mysql -u root -p hotel_db < advanced.sql
   ```

3. Create a new restricted account in the MySQL shell. Replace the password below
   with your own unique password; do not reuse your administrator password:

   ```sql
   CREATE USER 'hotel_app'@'localhost' IDENTIFIED BY 'choose-your-own-long-password';
   ```

   Apply its permissions from Command Prompt:

   ```bat
   mysql -u root -p hotel_db < security/grants.sql
   ```

   Use a new account: GRANT does not revoke permissions an existing account has.
   The account gets the table/view access and booking EXECUTE permission the app
   needs, without CREATE, DROP, ALTER, GRANT, or access to other databases.

4. Install Python dependencies in PowerShell:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python configure_admin.py
   ```

   The setup prompts for an admin password and confirmation, saves only its hash,
   and generates a session secret in the ignored `.env` file. Set `DB_PASSWORD`
   in `.env` to the restricted MySQL account's password. Default DB settings are
   `127.0.0.1:3306`, user `hotel_app`, database `hotel_db`.

5. Run `python app.py` and open http://127.0.0.1:5000. Sign in through the browser
   dialog with username `admin` and your chosen admin password. A missing admin
   configuration returns HTTP 503 and exposes no hotel records.

For access across a network, serve through HTTPS and set SESSION_COOKIE_SECURE=1.
HTTP Basic authentication must not be used over unencrypted network HTTP. Keep
MySQL reachable only from the app host. Do not expose Flask's debug server.

## Upgrade an existing installation (preserve records)

Stop the app and back up the database from PowerShell:

```powershell
mysqldump -u root -p --result-file=hotel_db_before_security.sql hotel_db
```

Store the dump securely outside the repository. The default backup filename is
ignored by Git because it may contain guest identity details.

If the database still has the original six tables (Guest contains city/state),
run migration 001 first. Skip 001 if Location and Guest.location_id already exist.
Then apply migration 002 and refresh the advanced objects in Command Prompt:

```bat
mysql -u root -p hotel_db < migrations/001_guest_locations.sql
mysql -u root -p hotel_db < migrations/002_database_integrity.sql
mysql -u root -p hotel_db < advanced.sql
```

Both migrations are one-time scripts. MySQL DDL commits implicitly: stop on any
error. Migration 002 validates existing records; if it finds invalid data, correct
those records explicitly and inspect which statements have already succeeded
before continuing. It never deletes guest, reservation, or payment history.
Do not run schema.sql or reload data.sql to upgrade an existing installation.
Fresh installations already contain both migrations' schema changes.

Run `python configure_admin.py` for this new authentication requirement, configure
the restricted database account above, and restart the updated application.
For shared/multiple worker deployments keep the generated SECRET_KEY consistent
across workers; the fallback key is random and lasts only for one process.

## Database design and booking rules

The seven base tables are Hotel, Location, Guest, RoomType, Room, Reservation,
and Payment. Guest references Location; city names may repeat across states,
and (city, state) is unique. Forms still accept city and state and resolve the
location automatically. guest_details_view joins the data for reads and reports.
See [normalization.md](normalization.md) for the BCNF dependencies and assumptions.

Room.status describes physical state (Available/Maintenance). Reservation dates
and active statuses determine availability. Reservation writes lock their room
row; triggers reject overlapping active stays and maintenance conflicts, including
writes through generic CRUD. Move or cancel active/future reservations before
putting a room under maintenance. Check-out on the next guest's check-in date is
allowed. Deadlocks/lock timeouts roll back the failed operation; retry if needed.

advanced.sql can be run again: it refreshes views, triggers and the procedure,
and creates missing indexes. Run it using the setup/migration account, not the
restricted runtime account.

## Security checks

See [SECURITY.md](SECURITY.md) for findings, fixes, and operational limits.
Run the integration suite against a local MySQL test server:

```bat
python -m unittest discover -s tests -v
```

Optional settings: TEST_DB_HOST, TEST_DB_PORT, TEST_DB_USER, TEST_DB_PASSWORD.
Tests use randomly named temporary databases, never the configured application
database. The test account needs CREATE/DROP DATABASE, CREATE/DROP USER and GRANT
permissions to validate the restricted runtime account. Use a disposable local
server for these checks.
