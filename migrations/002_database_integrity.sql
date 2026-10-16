-- One-time upgrade for the BCNF schema (run 001 first if needed).
-- Stop the app and back up hotel_db. CHECK additions validate existing data.
-- If invalid existing data causes a failure, correct it explicitly; do not
-- disable checks or delete history to force this migration through.
-- DDL commits implicitly; stop on any error. Run advanced.sql afterwards.
USE hotel_db;

ALTER TABLE Hotel
  ADD CONSTRAINT ck_hotel_text CHECK (hotel_name REGEXP '[^[:space:]]' AND address REGEXP '[^[:space:]]' AND city REGEXP '[^[:space:]]' AND manager_name REGEXP '[^[:space:]]');

ALTER TABLE Location
  ADD CONSTRAINT ck_location_text CHECK (city REGEXP '[^[:space:]]' AND state REGEXP '[^[:space:]]');

ALTER TABLE Guest
  ADD CONSTRAINT ck_guest_text CHECK (name REGEXP '[^[:space:]]' AND id_proof_type REGEXP '[^[:space:]]' AND id_proof_no REGEXP '[^[:space:]]'),
  ADD CONSTRAINT ck_guest_phone CHECK (phone REGEXP '^[6-9][0-9]{9}$');

ALTER TABLE RoomType
  ADD CONSTRAINT ck_type_text CHECK (type_name REGEXP '[^[:space:]]');

ALTER TABLE Room
  ADD CONSTRAINT ck_room_number CHECK (room_no REGEXP '[^[:space:]]'),
  ADD CONSTRAINT ck_room_status CHECK (status IN ('Available','Maintenance'));

ALTER TABLE Reservation
  ADD CONSTRAINT ck_reservation_dates CHECK (check_in >= '1000-01-01' AND MONTH(check_in) > 0 AND DAYOFMONTH(check_in) > 0 AND DAYOFMONTH(check_in) <= DAYOFMONTH(LAST_DAY(check_in)) AND check_out >= '1000-01-01' AND MONTH(check_out) > 0 AND DAYOFMONTH(check_out) > 0 AND DAYOFMONTH(check_out) <= DAYOFMONTH(LAST_DAY(check_out))),
  ADD CONSTRAINT ck_reservation_status CHECK (status IN ('Booked','Checked-in','Cancelled','Completed'));

ALTER TABLE Payment
  ADD CONSTRAINT ck_payment_date CHECK (payment_date >= '1000-01-01' AND MONTH(payment_date) > 0 AND DAYOFMONTH(payment_date) > 0 AND DAYOFMONTH(payment_date) <= DAYOFMONTH(LAST_DAY(payment_date))),
  ADD CONSTRAINT ck_payment_mode CHECK (mode IN ('Cash','UPI','Card','Net Banking'));

