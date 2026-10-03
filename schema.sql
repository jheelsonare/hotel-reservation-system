CREATE DATABASE IF NOT EXISTS hotel_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hotel_db;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS Payment;
DROP TABLE IF EXISTS Reservation;
DROP TABLE IF EXISTS Room;
DROP TABLE IF EXISTS RoomType;
DROP TABLE IF EXISTS Guest;
DROP TABLE IF EXISTS Hotel;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE Hotel (
  hotel_id INT AUTO_INCREMENT PRIMARY KEY,
  hotel_name VARCHAR(120) NOT NULL,
  address VARCHAR(255) NOT NULL,
  city VARCHAR(80) NOT NULL,
  manager_name VARCHAR(120) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE Guest (
  guest_id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  phone CHAR(10) NOT NULL UNIQUE,
  email VARCHAR(160) UNIQUE,
  city VARCHAR(80) NOT NULL,
  state VARCHAR(80) NOT NULL,
  id_proof_type VARCHAR(40) NOT NULL,
  id_proof_no VARCHAR(40) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE RoomType (
  type_id INT AUTO_INCREMENT PRIMARY KEY,
  type_name VARCHAR(60) NOT NULL UNIQUE,
  rent_per_day DECIMAL(10, 2) NOT NULL,
  CHECK (rent_per_day >= 0)
) ENGINE=InnoDB;

CREATE TABLE Room (
  room_id INT AUTO_INCREMENT PRIMARY KEY,
  hotel_id INT NOT NULL,
  type_id INT NOT NULL,
  room_no VARCHAR(20) NOT NULL,
  capacity TINYINT UNSIGNED NOT NULL,
  status ENUM('Available', 'Full', 'Maintenance') NOT NULL DEFAULT 'Available',
  UNIQUE KEY uq_hotel_room (hotel_id, room_no),
  CONSTRAINT fk_room_hotel FOREIGN KEY (hotel_id) REFERENCES Hotel(hotel_id),
  CONSTRAINT fk_room_type FOREIGN KEY (type_id) REFERENCES RoomType(type_id),
  CHECK (capacity > 0)
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
  CHECK (check_out > check_in)
) ENGINE=InnoDB;

CREATE TABLE Payment (
  payment_id INT AUTO_INCREMENT PRIMARY KEY,
  reservation_id INT NOT NULL,
  amount DECIMAL(10, 2) NOT NULL,
  payment_date DATE NOT NULL,
  mode ENUM('Cash', 'UPI', 'Card', 'Net Banking') NOT NULL,
  CONSTRAINT fk_payment_reservation FOREIGN KEY (reservation_id)
    REFERENCES Reservation(reservation_id),
  CHECK (amount >= 0)
) ENGINE=InnoDB;