USE hotel_db;

DROP VIEW IF EXISTS available_rooms_view;
CREATE VIEW available_rooms_view AS
SELECT rm.room_id, h.hotel_name, h.city, rm.room_no, rm.capacity,
       rt.type_name, rt.rent_per_day
FROM Room rm
JOIN Hotel h ON h.hotel_id = rm.hotel_id
JOIN RoomType rt ON rt.type_id = rm.type_id
WHERE rm.status = 'Available'
  AND NOT EXISTS (
    SELECT 1 FROM Reservation r
    WHERE r.room_id = rm.room_id
      AND r.status IN ('Booked','Checked-in')
      AND r.check_in <= CURDATE() AND r.check_out > CURDATE()
  );
-- Physical status is separate from date-specific occupancy.
-- Keep this view useful for today's availability without mutating Room.

DROP TRIGGER IF EXISTS trg_res_no_overlap_ins;
DROP TRIGGER IF EXISTS trg_res_no_overlap_upd;
DROP PROCEDURE IF EXISTS book_room;
DELIMITER //
CREATE TRIGGER trg_res_no_overlap_ins
BEFORE INSERT ON Reservation
FOR EACH ROW
BEGIN
  IF NEW.status IN ('Booked','Checked-in') AND EXISTS (
    SELECT 1 FROM Room WHERE room_id = NEW.room_id AND status = 'Maintenance'
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room is under maintenance';
  END IF;
  IF NEW.status IN ('Booked','Checked-in') AND EXISTS (
    SELECT 1 FROM Reservation
    WHERE room_id = NEW.room_id AND status IN ('Booked','Checked-in')
      AND check_in < NEW.check_out AND check_out > NEW.check_in
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room is already reserved for these dates';
  END IF;
END//
CREATE TRIGGER trg_res_no_overlap_upd
BEFORE UPDATE ON Reservation
FOR EACH ROW
BEGIN
  IF NEW.status IN ('Booked','Checked-in') AND EXISTS (
    SELECT 1 FROM Room WHERE room_id = NEW.room_id AND status = 'Maintenance'
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room is under maintenance';
  END IF;
  IF NEW.status IN ('Booked','Checked-in') AND EXISTS (
    SELECT 1 FROM Reservation
    WHERE reservation_id <> OLD.reservation_id
      AND room_id = NEW.room_id AND status IN ('Booked','Checked-in')
      AND check_in < NEW.check_out AND check_out > NEW.check_in
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room is already reserved for these dates';
  END IF;
END//
CREATE PROCEDURE book_room(IN p_guest_id INT, IN p_room_id INT,
                           IN p_check_in DATE, IN p_check_out DATE)
BEGIN
  DECLARE room_status VARCHAR(20);
  SELECT status INTO room_status FROM Room WHERE room_id = p_room_id FOR UPDATE;
  IF p_check_in >= p_check_out THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Check-out must be after check-in';
  ELSEIF p_check_in < CURDATE() THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Check-in cannot be in the past';
  ELSEIF NOT EXISTS (SELECT 1 FROM Guest WHERE guest_id = p_guest_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Guest does not exist';
  ELSEIF NOT EXISTS (SELECT 1 FROM Room WHERE room_id = p_room_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room does not exist';
  ELSEIF room_status = 'Maintenance' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room is under maintenance';
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

SET @sql = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics
          WHERE table_schema=DATABASE() AND table_name='Guest' AND index_name='idx_guest_city'),
  'SELECT 1',
  'CREATE INDEX idx_guest_city ON Guest(city)'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @sql = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics
          WHERE table_schema=DATABASE() AND table_name='Reservation' AND index_name='idx_reservation_status'),
  'SELECT 1',
  'CREATE INDEX idx_reservation_status ON Reservation(status)'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @sql = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics
          WHERE table_schema=DATABASE() AND table_name='Reservation' AND index_name='idx_reservation_check_in'),
  'SELECT 1',
  'CREATE INDEX idx_reservation_check_in ON Reservation(check_in)'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @sql = IF(
  EXISTS (SELECT 1 FROM information_schema.statistics
          WHERE table_schema=DATABASE() AND table_name='Reservation' AND index_name='idx_reservation_room_dates'),
  'SELECT 1',
  'CREATE INDEX idx_reservation_room_dates ON Reservation(room_id, check_in, check_out)'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
