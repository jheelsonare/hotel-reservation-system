-- One-time migration from the original six-table schema. Stop the app first.
-- Back up hotel_db before running. MySQL DDL commits implicitly; this script
-- is not transactional or rerunnable. No guests/reservations/payments are deleted.
USE hotel_db;

CREATE TABLE Location (
  location_id INT AUTO_INCREMENT PRIMARY KEY,
  city VARCHAR(80) NOT NULL,
  state VARCHAR(80) NOT NULL,
  UNIQUE KEY uq_location_city_state (city, state)
) ENGINE=InnoDB;

INSERT INTO Location (city, state)
SELECT DISTINCT city, state FROM Guest;

ALTER TABLE Guest ADD COLUMN location_id INT NULL AFTER email;
UPDATE Guest g JOIN Location l ON l.city=g.city AND l.state=g.state
SET g.location_id=l.location_id;

-- NOT NULL validates every guest was mapped before the original columns go away.
ALTER TABLE Guest MODIFY COLUMN location_id INT NOT NULL,
  ADD CONSTRAINT fk_guest_location FOREIGN KEY (location_id)
    REFERENCES Location(location_id);
ALTER TABLE Guest DROP COLUMN city, DROP COLUMN state;

CREATE OR REPLACE VIEW guest_details_view AS
SELECT g.guest_id, g.name, g.phone, g.email, l.city, l.state,
       g.id_proof_type, g.id_proof_no
FROM Guest g JOIN Location l ON l.location_id = g.location_id;

-- Now run advanced.sql to refresh views/procedures/triggers/indexes.
