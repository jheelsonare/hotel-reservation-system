# Normalization and BCNF in the Hotel Reservation System

## Why separate tables?

One large booking table would repeat guest contact details, hotel addresses,
room-type prices, and payments. This produces update, insertion, and deletion
anomalies. The implementation stores each fact with the entity it describes.
A reservation identifies one guest, one room, and one stay; multiple rooms
require multiple reservations. A reservation may have several payments.

## 1NF: atomic values

Do not store comma-separated rooms or repeated payment columns in one row.
Room, Reservation, and Payment use separate rows for separate facts.

## 2NF: no partial dependencies

For example, in a conceptual combined reservation/payment relation keyed by
(reservation_id, payment_id), stay details depend on reservation_id alone.
Separating reservation facts from payment facts removes that partial dependency.
Check every candidate key, not just the chosen primary key; a surrogate ID
alone does not establish a normal form.

## 3NF: no inappropriate transitive dependencies

Room stores hotel_id and type_id, while Hotel stores hotel facts and RoomType
stores the type name and daily rent. Thus hotel addresses and type prices are
not repeated in Room. Reservation references Guest and Room instead of copying
their descriptive facts.

## BCNF: every non-trivial determinant is a superkey

For every non-trivial functional dependency X -> Y, X must uniquely identify
an entire row. A candidate key is a minimal superkey.

The design assumes only the dependencies below and dependencies implied by
these keys. Further business rules must be checked before claiming BCNF.

| Relation | Candidate keys | Key determines |
| --- | --- | --- |
| Hotel | hotel_id | hotel_name, address, city, manager_name |
| Location | location_id; (city, state) | all location attributes |
| Guest | guest_id; phone | name, phone, email, location_id, identity details |
| RoomType | type_id; type_name | type_name, rent_per_day |
| Room | room_id; (hotel_id, room_no) | hotel_id, type_id, room_no, capacity, status |
| Reservation | reservation_id | guest_id, room_id, check_in, check_out, status |
| Payment | payment_id | reservation_id, amount, payment_date, mode |

All listed determinants are superkeys, so all seven base tables satisfy BCNF
under these assumptions. Guest.email is UNIQUE but nullable; it is not treated
as a classical candidate key because multiple NULL values are allowed.
No dependency from a guest name, identity-proof number, hotel name, or room
number alone is assumed. In particular, room numbers can repeat across hotels.

## Location change and its limits

Guest now stores location_id, referencing Location(location_id, city, state).
The UNIQUE(city, state) constraint reuses a city/state pair; different states
may have cities with the same name. There is deliberately no UNIQUE(city)
constraint and no assumed city -> state dependency. The Hotel table still
stores its city as a hotel attribute; it does not store a state.

The old Guest table was not automatically a BCNF violation merely because it
contained city and state. If city -> state had been a valid business rule,
that dependency would have violated both 3NF and BCNF there. City names are
not universally unique, so the application does not adopt that rule. This
change makes locations reusable and documents BCNF; it is not evidence that
all original tables required decomposition.

The representation change is lossless: every Guest has exactly one non-null
location_id referencing exactly one Location row. Joining on that key restores
the guest's city and state without adding or losing guest rows. Guest keys and
other foreign keys remain enforced, and the city/state pair is enforced as a
Location key.

## How joins restore readable guest information

```sql
SELECT g.guest_id, g.name, l.city, l.state
FROM Guest g
JOIN Location l ON l.location_id = g.location_id;
```

`guest_details_view` saves this join and exposes the original guest display
columns. Lists, searches, sorting, booking dropdowns, and reports read this
view. Guest writes resolve or create the Location row and save its ID in the
same transaction. Moving a guest to another city changes that guest's reference;
it does not change the shared location for other guests.

Reports demonstrate INNER, LEFT, RIGHT, and self joins, aggregation, HAVING,
and a CTE/subquery. The same-city self join matches both city and state.

## Existing databases

Use migrations/001_guest_locations.sql once, then advanced.sql. Do not run
schema.sql to upgrade: it recreates tables and deletes existing records.
See README.md for backup and execution instructions. The migration retains
guest IDs, city/state associations, reservations, and payments. Stored location
spelling follows the existing database's case/accent-insensitive collation.
