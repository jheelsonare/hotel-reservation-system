-- Run as a database administrator after schema.sql + data.sql + advanced.sql.
-- First create 'hotel_app'@'localhost' with a unique password interactively.
-- This script deliberately does not create an account with a default password.
-- Use a NEW application account with no previous grants. These GRANT statements
-- do not remove excessive permissions from an existing account.
GRANT SELECT, INSERT, UPDATE, DELETE ON hotel_db.Hotel TO 'hotel_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON hotel_db.Guest TO 'hotel_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON hotel_db.Room TO 'hotel_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON hotel_db.Reservation TO 'hotel_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON hotel_db.Payment TO 'hotel_app'@'localhost';
GRANT SELECT, INSERT (city, state), UPDATE (location_id) ON hotel_db.Location TO 'hotel_app'@'localhost';
GRANT SELECT ON hotel_db.RoomType TO 'hotel_app'@'localhost';
GRANT SELECT ON hotel_db.guest_details_view TO 'hotel_app'@'localhost';
GRANT SELECT ON hotel_db.available_rooms_view TO 'hotel_app'@'localhost';
GRANT EXECUTE ON PROCEDURE hotel_db.book_room TO 'hotel_app'@'localhost';
