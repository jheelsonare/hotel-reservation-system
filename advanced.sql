USE hotel_db;

DROP VIEW IF EXISTS available_rooms_view;
CREATE VIEW available_rooms_view AS
SELECT rm.room_id, h.hotel_name, h.city, rm.room_no, rm.capacity,
       rt.type_name, rt.rent_per_day
FROM Room rm
JOIN Hotel h ON h.hotel_id = rm.hotel_id
JOIN RoomType rt ON rt.type_id = rm.type_id
WHERE rm.status = 'Available';

DROP TRIGGER IF EXISTS after_reservation_insert;
DROP TRIGGER IF EXISTS after_reservation_update;
DELIMITER //
CREATE TRIGGER after_reservation_insert
AFTER INSERT ON Reservation
FOR EACH ROW
BEGIN
  UPDATE Room SET status = 'Full'
  WHERE room_id = NEW.room_id
    AND (SELECT COUNT(*) FROM Reservation
         WHERE room_id = NEW.room_id AND status IN ('Booked','Checked-in')) >= capacity;
END//
CREATE TRIGGER after_reservation_update
AFTER UPDATE ON Reservation
FOR EACH ROW
BEGIN
  UPDATE Room SET status = CASE
    WHEN (SELECT COUNT(*) FROM Reservation
          WHERE room_id = NEW.room_id AND status IN ('Booked','Checked-in')) >= capacity
    THEN 'Full' ELSE 'Available' END
  WHERE room_id = NEW.room_id;
  IF OLD.room_id <> NEW.room_id THEN
    UPDATE Room SET status = CASE
      WHEN (SELECT COUNT(*) FROM Reservation
            WHERE room_id = OLD.room_id AND status IN ('Booked','Checked-in')) >= capacity
      THEN 'Full' ELSE 'Available' END
    WHERE room_id = OLD.room_id;
  END IF;
END//
CREATE PROCEDURE book_room(IN p_guest_id INT, IN p_room_id INT,
                           IN p_check_in DATE, IN p_check_out DATE)
BEGIN
  IF p_check_in >= p_check_out THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Check-out must be after check-in';
  ELSEIF NOT EXISTS (SELECT 1 FROM Guest WHERE guest_id = p_guest_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Guest does not exist';
  ELSEIF NOT EXISTS (SELECT 1 FROM Room WHERE room_id = p_room_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room does not exist';
  ELSEIF EXISTS (SELECT 1 FROM Reservation WHERE room_id=p_room_id
      AND status IN ('Booked','Checked-in')
      AND check_in < p_check_out AND check_out > p_check_in) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room is already reserved';
  ELSE
    INSERT INTO Reservation(guest_id,room_id,check_in,check_out,status)
      VALUES(p_guest_id,p_room_id,p_check_in,p_check_out,'Booked');
  END IF;
END//
DELIMITER ;

CREATE INDEX idx_guest_city ON Guest(city);
CREATE INDEX idx_guest_phone ON Guest(phone);
CREATE INDEX idx_reservation_status ON Reservation(status);
CREATE INDEX idx_reservation_check_in ON Reservation(check_in);
