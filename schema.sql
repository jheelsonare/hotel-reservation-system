CREATE DATABASE IF NOT EXISTS hotel_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hotel_db;

DROP VIEW IF EXISTS guest_details_view;
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS Payment;
DROP TABLE IF EXISTS Reservation;
DROP TABLE IF EXISTS Room;
DROP TABLE IF EXISTS RoomType;
DROP TABLE IF EXISTS Guest;
DROP TABLE IF EXISTS Location;
DROP TABLE IF EXISTS Hotel;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE Hotel (
  hotel_id INT AUTO_INCREMENT PRIMARY KEY,
  hotel_name VARCHAR(120) NOT NULL,
  address VARCHAR(255) NOT NULL,
  city VARCHAR(80) NOT NULL,
  manager_name VARCHAR(120) NOT NULL,
  CONSTRAINT ck_hotel_text CHECK (hotel_name REGEXP '[^[:space:]]' AND address REGEXP '[^[:space:]]' AND city REGEXP '[^[:space:]]' AND manager_name REGEXP '[^[:space:]]')
) ENGINE=InnoDB;

CREATE TABLE Location (
  location_id INT AUTO_INCREMENT PRIMARY KEY,
  city VARCHAR(80) NOT NULL,
  state VARCHAR(80) NOT NULL,
  UNIQUE KEY uq_location_city_state (city, state),
  CONSTRAINT ck_location_text CHECK (city REGEXP '[^[:space:]]' AND state REGEXP '[^[:space:]]')
) ENGINE=InnoDB;

CREATE TABLE Guest (
  guest_id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  phone CHAR(10) NOT NULL UNIQUE,
  email VARCHAR(160) UNIQUE,
  location_id INT NOT NULL,
  id_proof_type VARCHAR(40) NOT NULL,
  id_proof_no VARCHAR(40) NOT NULL,
  CONSTRAINT fk_guest_location FOREIGN KEY (location_id) REFERENCES Location(location_id),
  CONSTRAINT ck_guest_text CHECK (name REGEXP '[^[:space:]]' AND id_proof_type REGEXP '[^[:space:]]' AND id_proof_no REGEXP '[^[:space:]]'),
  CONSTRAINT ck_guest_phone CHECK (phone REGEXP '^[6-9][0-9]{9}$')
) ENGINE=InnoDB;

CREATE TABLE RoomType (
  type_id INT AUTO_INCREMENT PRIMARY KEY,
  type_name VARCHAR(60) NOT NULL UNIQUE,
  rent_per_day DECIMAL(10, 2) NOT NULL,
  CHECK (rent_per_day >= 0),
  CONSTRAINT ck_type_text CHECK (type_name REGEXP '[^[:space:]]')
) ENGINE=InnoDB;

CREATE TABLE Room (
  room_id INT AUTO_INCREMENT PRIMARY KEY,
  hotel_id INT NOT NULL,
  type_id INT NOT NULL,
  room_no VARCHAR(20) NOT NULL,
  capacity TINYINT UNSIGNED NOT NULL,
  status ENUM('Available', 'Maintenance') NOT NULL DEFAULT 'Available',
  UNIQUE KEY uq_hotel_room (hotel_id, room_no),
  CONSTRAINT fk_room_hotel FOREIGN KEY (hotel_id) REFERENCES Hotel(hotel_id),
  CONSTRAINT fk_room_type FOREIGN KEY (type_id) REFERENCES RoomType(type_id),
  CHECK (capacity > 0),
  CONSTRAINT ck_room_number CHECK (room_no REGEXP '[^[:space:]]'),
  CONSTRAINT ck_room_status CHECK (status IN ('Available','Maintenance'))
) ENGINE=InnoDB;

CREATE TABLE Reservation (
  reservation_id INT AUTO_INCREMENT PRIMARY KEY,
  guest_id INT NOT NULL,
  room_id INT NOT NULL,
  check_in DATE NOT NULL,
  check_out DATE NOT NULL,
  status ENUM('Booked', 'Checked-in', 'Cancelled', 'Completed') NOT NULL DEFAULT 'Booked',
  CONSTRAINT fk_reservation_guest FOREIGN KEY (guest_id) REFERENCES Guest(guest_id),
  CONSTRAINT fk_reservation_room FOREIGN KEY (room_id) REFERENCES Room(room_id),
  CHECK (check_out > check_in),
  CONSTRAINT ck_reservation_dates CHECK (check_in >= '1000-01-01' AND MONTH(check_in) > 0 AND DAYOFMONTH(check_in) > 0 AND DAYOFMONTH(check_in) <= DAYOFMONTH(LAST_DAY(check_in)) AND check_out >= '1000-01-01' AND MONTH(check_out) > 0 AND DAYOFMONTH(check_out) > 0 AND DAYOFMONTH(check_out) <= DAYOFMONTH(LAST_DAY(check_out))),
  CONSTRAINT ck_reservation_status CHECK (status IN ('Booked','Checked-in','Cancelled','Completed'))
) ENGINE=InnoDB;

CREATE TABLE Payment (
  payment_id INT AUTO_INCREMENT PRIMARY KEY,
  reservation_id INT NOT NULL,
  amount DECIMAL(10, 2) NOT NULL,
  payment_date DATE NOT NULL,
  mode ENUM('Cash', 'UPI', 'Card', 'Net Banking') NOT NULL,
  CONSTRAINT fk_payment_reservation FOREIGN KEY (reservation_id)
    REFERENCES Reservation(reservation_id),
  CHECK (amount >= 0),
  CONSTRAINT ck_payment_date CHECK (payment_date >= '1000-01-01' AND MONTH(payment_date) > 0 AND DAYOFMONTH(payment_date) > 0 AND DAYOFMONTH(payment_date) <= DAYOFMONTH(LAST_DAY(payment_date))),
  CONSTRAINT ck_payment_mode CHECK (mode IN ('Cash','UPI','Card','Net Banking'))
) ENGINE=InnoDB;
