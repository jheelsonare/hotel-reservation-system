"""Real-MySQL integration tests; only randomly named temporary databases are used."""
import os
import base64
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta

import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash
import app as hotel

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {
    'host': os.getenv('TEST_DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('TEST_DB_PORT', '3306')),
    'user': os.getenv('TEST_DB_USER', 'root'),
    'password': os.getenv('TEST_DB_PASSWORD', ''),
}


def run_script(conn, text, database):
    """Execute mysql-client SQL, including DELIMITER-marked routine bodies."""
    delimiter, buffer = ';', ''
    cur = conn.cursor()
    try:
        for line in text.replace('hotel_db', database).splitlines():
            if line.strip().upper().startswith('DELIMITER '):
                if buffer.strip():
                    raise AssertionError('Unexpected SQL before DELIMITER')
                delimiter = line.strip().split()[1]
                continue
            if not line.strip() or line.lstrip().startswith('--'):
                continue
            buffer += line + '\n'
            if buffer.rstrip().endswith(delimiter):
                cur.execute(buffer.rstrip()[:-len(delimiter)])
                if cur.with_rows:
                    cur.fetchall()
                while cur.nextset():
                    if cur.with_rows:
                        cur.fetchall()
                buffer = ''
        if buffer.strip():
            raise AssertionError('Unterminated SQL statement')
        conn.commit()
    finally:
        cur.close()


TEST_USERNAME, TEST_PASSWORD = "test-admin", "integration-only-password"


def authenticated_client():
    client = hotel.app.test_client()
    encoded = base64.b64encode(f"{TEST_USERNAME}:{TEST_PASSWORD}".encode()).decode()
    client.environ_base["HTTP_AUTHORIZATION"] = "Basic " + encoded
    return client


class MySQLTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_config = hotel.DB_CONFIG.copy()
        cls.original_auth = (hotel.app.config["ADMIN_USERNAME"], hotel.app.config["ADMIN_PASSWORD_HASH"])
        hotel.app.config.update(ADMIN_USERNAME=TEST_USERNAME,
            ADMIN_PASSWORD_HASH=generate_password_hash(TEST_PASSWORD, method="pbkdf2:sha256:1000"))
        cls.db = 'hotel_test_' + uuid.uuid4().hex[:16]
        cls.conn = mysql.connector.connect(**CONFIG)
        try:
            run_script(cls.conn, (ROOT/'schema.sql').read_text(), cls.db)
            run_script(cls.conn, (ROOT/'data.sql').read_text(), cls.db)
            run_script(cls.conn, (ROOT/'advanced.sql').read_text(), cls.db)
            # Advanced objects must remain safe to refresh.
            run_script(cls.conn, (ROOT/'advanced.sql').read_text(), cls.db)
        except Exception:
            cls.conn.cursor().execute(f'DROP DATABASE IF EXISTS `{cls.db}`')
            cls.conn.close()
            raise
        hotel.DB_CONFIG = dict(CONFIG, database=cls.db)
        hotel.app.config.update(TESTING=True, SECRET_KEY='integration-test-only')

    @classmethod
    def tearDownClass(cls):
        hotel.DB_CONFIG = cls.original_config
        hotel.app.config.update(ADMIN_USERNAME=cls.original_auth[0], ADMIN_PASSWORD_HASH=cls.original_auth[1])
        cur = cls.conn.cursor()
        cur.execute(f'DROP DATABASE `{cls.db}`')
        cur.close()
        cls.conn.close()

    def query(self, sql, params=()):
        return hotel.query(sql, params)


class BCNFIntegrationTests(MySQLTestCase):
    def test_seed_and_location_foreign_key(self):
        self.assertEqual(self.query('SELECT COUNT(*) n FROM Guest')[0]['n'], 1200)
        self.assertEqual(self.query('SELECT COUNT(*) n FROM guest_details_view')[0]['n'], 1200)
        self.assertEqual(self.query('SELECT COUNT(*) n FROM Location')[0]['n'], 33)
        self.assertEqual(self.query('SELECT COUNT(*) n FROM Reservation')[0]['n'], 1500)
        with self.assertRaises(Error):
            hotel.execute('UPDATE Guest SET location_id=999999 WHERE guest_id=1')

    def test_guest_create_edit_location_reuse_and_distinct_states(self):
        base = ['Location Test', '9890000001', 'loc-test@example.test',
                'Shared City', 'State One', 'Test', 'TEST1']
        guest1 = hotel.save_guest(base)
        guest2 = hotel.save_guest([*base[:1], '9890000002', 'loc-test2@example.test', *base[3:]])
        ids = self.query('SELECT location_id FROM Guest WHERE guest_id IN (%s,%s)', (guest1, guest2))
        self.assertEqual(ids[0]['location_id'], ids[1]['location_id'])
        changed = base.copy()
        changed[4] = 'State Two'
        hotel.save_guest(changed, guest1)
        rows = self.query('SELECT guest_id, city, state FROM guest_details_view WHERE guest_id IN (%s,%s) ORDER BY guest_id', (guest1, guest2))
        self.assertEqual([r['state'] for r in rows], ['State Two', 'State One'])
        hotel.execute('DELETE FROM Guest WHERE guest_id IN (%s,%s)', (guest1, guest2))
        hotel.execute("DELETE FROM Location WHERE city='Shared City'")

    def test_failed_guest_write_rolls_back_new_location(self):
        existing_phone = self.query('SELECT phone FROM Guest WHERE guest_id=1')[0]['phone']
        with self.assertRaises(Error):
            hotel.save_guest(['Duplicate', existing_phone, None, 'Rollback City', 'Rollback State', 'Test', 'X'])
        self.assertEqual(self.query("SELECT COUNT(*) n FROM Location WHERE city='Rollback City'")[0]['n'], 0)

    def test_guest_forms_search_sort_and_delete(self):
        client = authenticated_client()
        self.assertEqual(client.get('/guests/new').status_code, 200)
        with client.session_transaction() as session:
            token = session['csrf_token']
        payload = dict(name='Form Guest', phone='9890000003', email='form@example.test',
                       city='Form City', state='Form State', id_proof_type='Test',
                       id_proof_no='FORM1', csrf_token=token)
        self.assertEqual(client.post('/guests/new', data=payload).status_code, 302)
        row = self.query("SELECT * FROM guest_details_view WHERE phone='9890000003'")[0]
        guest_id = row['guest_id']
        self.assertEqual(client.get(f'/guests/{guest_id}/edit').status_code, 200)
        self.assertIn(b'Form Guest', client.get('/guests?q=Form+City&sort=state').data)
        payload.update(city='Indore', state='Madhya Pradesh')
        self.assertEqual(client.post(f'/guests/{guest_id}/edit', data=payload).status_code, 302)
        self.assertEqual(self.query('SELECT city FROM guest_details_view WHERE guest_id=%s', (guest_id,))[0]['city'], 'Indore')
        self.assertEqual(client.post(f'/guests/{guest_id}/delete', data={'csrf_token':token}).status_code, 302)
        self.assertEqual(self.query('SELECT * FROM Guest WHERE guest_id=%s', (guest_id,)), [])
        hotel.execute("DELETE FROM Location WHERE city='Form City'")

    def test_all_pages_and_report_sql(self):
        client = authenticated_client()
        for route in ['/', '/guests', '/hotels', '/rooms', '/reservations', '/payments',
                      '/reservations/book', '/reports']:
            response = client.get(route)
            self.assertEqual(response.status_code, 200, route)
            self.assertNotIn(b'temporarily unavailable', response.data, route)
            self.assertNotIn(b'could not complete', response.data, route)
        # The shared view reconstructs the location columns in all reports.
        response = client.get('/reports')
        self.assertIn(b'guest_details_view', response.data)

    def test_new_guest_booking_and_overlap_guard(self):
        client = authenticated_client()
        client.get('/reservations/book')
        with client.session_transaction() as session:
            token = session['csrf_token']
        cin = (date.today() + timedelta(days=2000)).isoformat()
        cout = (date.today() + timedelta(days=2002)).isoformat()
        response = client.post('/reservations/book', data=dict(
            csrf_token=token, new_guest='1', guest_name='Booking Guest',
            guest_phone='9890000004', guest_email='booking@example.test',
            guest_city='Booking City', guest_state='Booking State',
            guest_id_proof_type='Test', guest_id_proof_no='BOOK1',
            room_type_id='1', check_in=cin, check_out=cout,
        ))
        self.assertEqual(response.status_code, 302)
        guest = self.query("SELECT * FROM guest_details_view WHERE phone='9890000004'")[0]
        booking = self.query('SELECT * FROM Reservation WHERE guest_id=%s', (guest['guest_id'],))[0]
        self.assertEqual(guest['city'], 'Booking City')
        with self.assertRaises(Error):
            hotel.execute('INSERT INTO Reservation(guest_id,room_id,check_in,check_out) VALUES(%s,%s,%s,%s)',
                          (guest['guest_id'], booking['room_id'], cin, cout))
        hotel.execute('DELETE FROM Reservation WHERE reservation_id=%s', (booking['reservation_id'],))
        hotel.execute('DELETE FROM Guest WHERE guest_id=%s', (guest['guest_id'],))
        hotel.execute("DELETE FROM Location WHERE city='Booking City'")

    def test_generator_output_loads(self):
        database = 'hotel_gen_' + uuid.uuid4().hex[:16]
        conn = mysql.connector.connect(**CONFIG)
        try:
            run_script(conn, (ROOT/'schema.sql').read_text(), database)
            with tempfile.TemporaryDirectory() as folder:
                subprocess.run([sys.executable, str(ROOT/'generate_data.py')], cwd=folder, check=True, capture_output=True)
                run_script(conn, (Path(folder)/'data.sql').read_text(), database)
            cur = conn.cursor()
            cur.execute('SELECT COUNT(*) FROM Guest g JOIN Location l ON l.location_id=g.location_id')
            self.assertEqual(cur.fetchone()[0], 1200)
            cur.close()
        finally:
            conn.cursor().execute(f'DROP DATABASE IF EXISTS `{database}`')
            conn.close()

    def test_legacy_migration_preserves_records(self):
        database = 'hotel_old_' + uuid.uuid4().hex[:16]
        conn = mysql.connector.connect(**CONFIG)
        try:
            run_script(conn, (ROOT/'tests/fixtures/legacy_schema.sql').read_text(), database)
            run_script(conn, """
INSERT INTO Hotel(hotel_name,address,city,manager_name) VALUES('Test Hotel','Road','Test City','Manager');
INSERT INTO RoomType(type_name,rent_per_day) VALUES('Test Type',1000);
INSERT INTO Room(hotel_id,type_id,room_no,capacity) VALUES(1,1,'101',2);
INSERT INTO Guest(name,phone,email,city,state,id_proof_type,id_proof_no) VALUES
('A','9890000011',NULL,'Same City','State One','Test','1'),
('B','9890000012',NULL,'Same City','State Two','Test','2'),
('C','9890000013',NULL,'Same City','State One','Test','3');
INSERT INTO Reservation(guest_id,room_id,check_in,check_out) VALUES(1,1,'2035-01-01','2035-01-03');
INSERT INTO Payment(reservation_id,amount,payment_date,mode) VALUES(1,2000,'2035-01-01','UPI');
CREATE INDEX idx_guest_city ON Guest(city);
""", database)
            cur = conn.cursor()
            snapshots = {}
            for table in ['Hotel', 'RoomType', 'Room', 'Guest', 'Reservation', 'Payment']:
                cur.execute(f'SELECT * FROM {table} ORDER BY 1')
                snapshots[table] = cur.fetchall()
            run_script(conn, (ROOT/'migrations/001_guest_locations.sql').read_text(), database)
            run_script(conn, (ROOT/'migrations/002_database_integrity.sql').read_text(), database)
            run_script(conn, (ROOT/'advanced.sql').read_text(), database)
            for table, expected in snapshots.items():
                source = 'guest_details_view' if table == 'Guest' else table
                cur.execute(f'SELECT * FROM {source} ORDER BY 1')
                self.assertEqual(cur.fetchall(), expected, table)
            cur.execute('SELECT COUNT(*) FROM Location')
            self.assertEqual(cur.fetchone()[0], 2)
            cur.close()
        finally:
            conn.cursor().execute(f'DROP DATABASE IF EXISTS `{database}`')
            conn.close()


if __name__ == '__main__':
    unittest.main()
