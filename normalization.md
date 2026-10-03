# Normalisation write-up

## Unnormalised booking (UNF)

`Booking(BookingNo, GuestName, Phone, Email, {RoomNo, RoomType, RentPerDay}, HotelName, CheckIn, CheckOut, {PaymentMode, PaymentAmount})`

Example Indian rows:

| BookingNo | GuestName | Phone | Rooms | HotelName | Payment |
|---|---|---|---|---|---|
| 1001 | Aanya Sharma | 9876543210 | 101, 102 | Ganga Nivas | UPI: 1200 |
| 1002 | Arjun Patel | 9123456789 | 202 | Kashi Bhavan | Card: 2000 |

The repeating room/payment groups violate 1NF.  Useful dependencies include
`GuestID -> GuestName, Phone, Email, City, State`,
`HotelID -> HotelName, Address, City, ManagerName`,
`RoomID -> HotelID, TypeID, RoomNo, Capacity, Status`,
`TypeID -> TypeName, RentPerDay`, and
`ReservationID -> GuestID, RoomID, CheckIn, CheckOut, Status`.

## UNF -> 1NF

Make every room/payment a separate atomic row, with one value per cell. A
reservation row identifies one guest, one room, and one stay; a payment row
identifies one payment. This removes repeating groups and makes inserts and
searches predictable.

## 1NF -> 2NF

Move attributes that depend only on part of a conceptual composite key into
their own relations: Guest, Hotel, RoomType, Room, Reservation, and Payment.
Room details no longer repeat for every reservation, and payment details no
longer repeat for every room.

## 2NF -> 3NF

Remove transitive dependencies: `Room.hotel_id` determines hotel facts and
`Room.type_id` determines rate/type facts, so those facts are stored in Hotel
and RoomType. Reservation stores only foreign keys and stay facts. Payment
stores only its reservation reference and payment facts.

This avoids update anomalies (one hotel address or rent to update), insert
anomalies (a room type can exist before its first booking), and delete
anomalies (deleting a reservation does not erase the guest, hotel, or room
type).
