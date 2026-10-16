# Database security review

## Findings and changes

| Finding | Change |
| --- | --- |
| All guest, reservation and payment routes were accessible without authentication | Required administrator HTTP Basic authentication for every route; missing password-hash configuration fails closed |
| Predictable session-signing fallback | A new random per-process secret when absent, or a configured random secret of at least 32 characters; known example/short values are rejected |
| Default runtime database user was root | Default hotel_app user and explicit least-privilege grants; views and book_room use SQL SECURITY INVOKER |
| Database exception text could contain submitted guest values | Log MySQL error numbers and fixed context, without exception bodies/tracebacks |
| Invalid dates/amounts were mainly left to database coercion | Strict session SQL mode, explicit date/numeric/length validation, and CHECK constraints for blank fields, phone format, valid dates and enum values |
| Booked rooms could be switched into maintenance | A Room trigger rejects maintenance while active/future reservations remain |
| Generic reservation CRUD did not explicitly lock its parent room | Insert/update triggers now lock that room until transaction completion; existing overlap guards remain |
| Unbounded request/search inputs and lock waits | 64 KiB request-body limit, 200-character search limit, 5-second connection/lock waits and SELECT execution limit |
| Browsers could cache guest identity data | Cache-Control: no-store, HttpOnly/SameSite cookies, frame denial and content-type protection |
| Database backups could be accidentally committed | Ignore default backup names and backups/; document secure backup storage |

User-entered SQL values were already parameterized and table/sort identifiers
were allowlisted. The review did not find a demonstrated SQL injection in those
paths. Regression tests verify malicious search/sort/name payloads remain data.
Foreign keys and nonnegative amount checks remain enforced.

## Configuration and deployment

- Run configure_admin.py locally to create the administrator password hash and
  session secret. No password or generated secret belongs in Git. Configure
  DB_PASSWORD separately for the restricted MySQL user.
- HTTP Basic credentials need HTTPS when crossing a network. Local loopback HTTP
  is for the class demo. TLS termination, MySQL bind/firewall rules, and database
  account provisioning are deployment tasks; the repository commit does not
  change an existing server's settings or users.
- Failed submitted logins are limited to five per IP per minute in each process.
  Use a trusted reverse proxy for distributed rate limiting in a multi-worker
  deployment. The app does not trust arbitrary forwarded-IP headers.
- The project has one trusted demo administrator. It does not implement separate
  staff permissions, an immutable accounting ledger, or per-user audit history.
  CRUD intentionally allows this administrator to edit/delete permitted records.
- The SELECT execution limit is not a deadline for every kind of SQL statement.
  Lock waits and connection setup have separate limits. Runtime grants exclude
  schema changes and administration.
- Stored guest identity details and backups are not encrypted by this change.
  Use sample/masked identities for demonstrations and restrict real database and
  backup access. Use managed encryption/TLS when deploying with real guest data.
- Deadlocks may reject a conflicting transaction. The app rolls back rather than
  silently committing a partial booking. Retrying an operation is appropriate;
  the tests require at most one conflicting booking to commit.

## Validation

The MySQL 8 integration suite covers fresh setup, generated sample data, guest
CRUD, booking, reports, migration preservation, unauthenticated access, CSRF,
login throttling, SQL injection payloads, invalid dates/amounts, strict sessions,
CHECK constraints, maintenance conflicts, simultaneous overlapping bookings under
READ COMMITTED and REPEATABLE READ, and the restricted account's permitted CRUD
and rejected schema/admin access.

Upgrade instructions are in README.md. Stop the app, back up, apply required
migrations and advanced.sql, configure authentication, then restart. Existing
invalid rows cause the integrity migration to stop instead of discarding data.

Reference documentation:
- [MySQL locking reads](https://dev.mysql.com/doc/refman/8.0/en/innodb-locking-reads.html)
- [MySQL stored-program restrictions](https://dev.mysql.com/doc/refman/8.0/en/stored-program-restrictions.html)
- [Flask security considerations](https://flask.palletsprojects.com/en/stable/web-security/)
