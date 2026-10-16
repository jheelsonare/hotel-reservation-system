"""Regression checks for database access control and integrity."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import threading
from pathlib import Path
import mysql.connector
from mysql.connector import Error
import app as hotel
from test_bcnf import MySQLTestCase, authenticated_client, CONFIG, ROOT, run_script, TEST_USERNAME, TEST_PASSWORD


class DatabaseSecurityTests(MySQLTestCase):
    def setUp(self):
        hotel._auth_failures.clear()

    def test_unauthenticated_reads_and_writes_are_blocked(self):
        client = hotel.app.test_client()
        for route in ['/', '/guests', '/reports', '/payments', '/reservations/book']:
            response = client.get(route)
            self.assertEqual(response.status_code, 401, route)
            self.assertNotIn(b'id_proof_no', response.data)
        self.assertEqual(client.post('/guests/1/delete').status_code, 401)
        self.assertEqual(client.post('/payments/new').status_code, 401)
        self.assertEqual(self.query('SELECT COUNT(*) n FROM Guest')[0]['n'], 1200)

    def test_missing_auth_configuration_fails_closed(self):
        configured = hotel.app.config['ADMIN_PASSWORD_HASH']
        try:
            hotel.app.config['ADMIN_PASSWORD_HASH'] = ''
            self.assertEqual(authenticated_client().get('/').status_code, 503)
        finally:
            hotel.app.config['ADMIN_PASSWORD_HASH'] = configured

    def test_wrong_password_is_throttled(self):
        client = hotel.app.test_client()
        header = 'Basic ' + base64.b64encode(f'{TEST_USERNAME}:wrong-password'.encode()).decode()
        for _ in range(5):
            self.assertEqual(client.get('/guests', headers={'Authorization':header}).status_code, 401)
        self.assertEqual(client.get('/guests', headers={'Authorization':header}).status_code, 429)

    def test_sensitive_pages_are_not_cached(self):
        response = authenticated_client().get('/guests')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertNotEqual(hotel.app.secret_key, 'change-this-secret')

    def test_sql_injection_payloads_are_data(self):
        client = authenticated_client()
        response = client.get('/guests', query_string={'q':"' OR 1=1; DROP TABLE Guest; --", 'sort':'name`; DROP TABLE Guest; --'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'No records found', response.data)
        self.assertEqual(self.query('SELECT COUNT(*) n FROM Guest')[0]['n'], 1200)
        name = "O'Brien'); DROP TABLE Payment; --"
        guest_id = hotel.save_guest([name,'9891111001',None,'Indore','Madhya Pradesh','Test','SEC1'])
        self.assertEqual(self.query('SELECT name FROM Guest WHERE guest_id=%s',(guest_id,))[0]['name'], name)
        self.assertTrue(self.query('SELECT COUNT(*) n FROM Payment')[0]['n'] > 0)
        hotel.execute('DELETE FROM Guest WHERE guest_id=%s',(guest_id,))

    def test_authenticated_write_still_requires_csrf(self):
        client = authenticated_client()
        self.assertEqual(client.post('/guests/1/delete', data={'csrf_token':'forged'}).status_code, 302)
        self.assertEqual(self.query('SELECT guest_id FROM Guest WHERE guest_id=1')[0]['guest_id'], 1)

    def test_invalid_payment_and_room_inputs_rejected_before_write(self):
        for amount in ['-1', 'NaN', 'Infinity', '999999999', '1.001', 'not-money']:
            self.assertIsNotNone(hotel.validate('payments', ['1',amount,'2026-10-16','UPI']), amount)
        self.assertIsNotNone(hotel.validate('payments', ['1' * 5000,'1250.50','2026-10-16','UPI']))
        self.assertIsNone(hotel.validate('payments', ['1','1250.50','2026-10-16','UPI']))
        self.assertIsNotNone(hotel.validate('payments', ['1','1250.50','2026-02-30','UPI']))
        self.assertIsNotNone(hotel.validate('rooms', ['1','1','101','-1','Available']))
        self.assertIsNotNone(hotel.validate('rooms', ['1','1','101','256','Available']))
        self.assertIsNotNone(hotel.validate('reservations', ['1','1','2026-13-01','2026-14-01','Booked']))
        client = authenticated_client()
        client.get('/payments/new')
        with client.session_transaction() as session:
            token=session['csrf_token']
        before=self.query('SELECT COUNT(*) n FROM Payment')[0]['n']
        response=client.post('/payments/new', data=dict(csrf_token=token,reservation_id=1,amount='NaN',payment_date='2026-10-16',mode='UPI'))
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Amount must be',response.data)
        self.assertEqual(self.query('SELECT COUNT(*) n FROM Payment')[0]['n'],before)

    def test_strict_sessions_and_database_checks(self):
        row=self.query('SELECT @@sql_mode modes, @@max_execution_time max_time, @@innodb_lock_wait_timeout lock_time')[0]
        self.assertIn('STRICT_TRANS_TABLES',row['modes'])
        self.assertEqual(row['max_time'],5000)
        self.assertEqual(row['lock_time'],5)
        with self.assertRaises(Error):
            hotel.execute("UPDATE Guest SET phone='abc' WHERE guest_id=1")
        with self.assertRaises(Error):
            hotel.execute("UPDATE Guest SET name='   ' WHERE guest_id=1")
        with self.assertRaises(Error):
            hotel.execute("UPDATE Payment SET amount=-10 WHERE payment_id=1")
        # Direct clients can turn off strict mode; CHECKs still reject empty enum values and zero dates.
        conn=mysql.connector.connect(**CONFIG,database=self.db)
        cur=conn.cursor();cur.execute("SET SESSION sql_mode=''")
        try:
            for sql in ["UPDATE Room SET status='invalid' WHERE room_id=900",
                        "UPDATE Payment SET mode='invalid' WHERE payment_id=1",
                        "UPDATE Payment SET payment_date='0000-00-00' WHERE payment_id=1",
                        "UPDATE Payment SET payment_date='2026-00-20' WHERE payment_id=1",
                        "UPDATE Reservation SET check_in='2026-01-00' WHERE reservation_id=1",
                        "UPDATE Reservation SET status='invalid' WHERE reservation_id=1",
                        "UPDATE Reservation SET check_in='0000-00-00' WHERE reservation_id=1"]:
                with self.assertRaises(Error,msg=sql):cur.execute(sql)
                conn.rollback()
            cur.execute("SET SESSION sql_mode='ALLOW_INVALID_DATES'")
            with self.assertRaises(Error):
                cur.execute("UPDATE Payment SET payment_date='2026-02-30' WHERE payment_id=1")
            conn.rollback()
            with self.assertRaises(Error):
                cur.execute("UPDATE Guest SET name=CHAR(9) WHERE guest_id=1")
            conn.rollback()
        finally:cur.close();conn.close()

    def test_room_with_reservation_cannot_enter_maintenance(self):
        cin=(date.today()+timedelta(days=2500)).isoformat()
        cout=(date.today()+timedelta(days=2502)).isoformat()
        reservation=hotel.execute('INSERT INTO Reservation(guest_id,room_id,check_in,check_out) VALUES(1,900,%s,%s)',(cin,cout))
        try:
            with self.assertRaises(Error):hotel.execute("UPDATE Room SET status='Maintenance' WHERE room_id=900")
            self.assertEqual(self.query('SELECT status FROM Room WHERE room_id=900')[0]['status'],'Available')
        finally:hotel.execute('DELETE FROM Reservation WHERE reservation_id=%s',(reservation,))
        hotel.execute("UPDATE Room SET status='Maintenance' WHERE room_id=900")
        try:
            with self.assertRaises(Error):hotel.execute('INSERT INTO Reservation(guest_id,room_id,check_in,check_out) VALUES(1,900,%s,%s)',(cin,cout))
        finally:hotel.execute("UPDATE Room SET status='Available' WHERE room_id=900")

    def test_parallel_overlap_inserts_and_stale_snapshot(self):
        cin=(date.today()+timedelta(days=2600)).isoformat()
        cout=(date.today()+timedelta(days=2602)).isoformat()
        for isolation in ['READ COMMITTED','REPEATABLE READ']:
            barrier=threading.Barrier(2)
            def reserve(guest):
                conn=mysql.connector.connect(**CONFIG,database=self.db)
                cur=conn.cursor();cur.execute('SET SESSION innodb_lock_wait_timeout=3')
                conn.start_transaction(isolation_level=isolation)
                cur.execute('SELECT COUNT(*) FROM Reservation');cur.fetchall()
                barrier.wait(timeout=5)
                try:
                    cur.execute('INSERT INTO Reservation(guest_id,room_id,check_in,check_out) VALUES(%s,899,%s,%s)',(guest,cin,cout))
                    conn.commit();return True
                except Error:
                    conn.rollback();return False
                finally:cur.close();conn.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(reserve,guest) for guest in [1,2]]
                self.assertEqual(sum(f.result(timeout=10) for f in futures),1,isolation)
            self.assertEqual(self.query('SELECT COUNT(*) n FROM Reservation WHERE room_id=899 AND check_in=%s',(cin,))[0]['n'],1)
            hotel.execute('DELETE FROM Reservation WHERE room_id=899 AND check_in=%s',(cin,))

    def test_procedure_and_views_use_invoker_rights(self):
        views=self.query("SELECT SECURITY_TYPE FROM information_schema.views WHERE TABLE_SCHEMA=%s",(self.db,))
        self.assertTrue(views)
        self.assertTrue(all(v['SECURITY_TYPE']=='INVOKER' for v in views))
        routines=self.query("SELECT SECURITY_TYPE FROM information_schema.routines WHERE ROUTINE_SCHEMA=%s AND ROUTINE_NAME='book_room'",(self.db,))
        self.assertEqual(routines[0]['SECURITY_TYPE'],'INVOKER')


    def test_restricted_account_runs_app_without_ddl_access(self):
        import secrets
        username='hotel_limited_'+secrets.token_hex(5)
        password=secrets.token_urlsafe(32)
        admin=mysql.connector.connect(**CONFIG,database=self.db)
        cur=admin.cursor()
        original=hotel.DB_CONFIG.copy()
        try:
            cur.execute("CREATE USER %s@'localhost' IDENTIFIED BY %s",(username,password))
            grants=(ROOT/'security/grants.sql').read_text().replace("'hotel_app'@'localhost'",f"'{username}'@'localhost'")
            run_script(admin,grants,self.db)
            hotel.DB_CONFIG=dict(CONFIG,database=self.db,user=username,password=password)
            client=authenticated_client()
            for route in ['/','/guests','/reports','/reservations/book']:
                response=client.get(route)
                self.assertEqual(response.status_code,200,route)
                self.assertNotIn(b'temporarily unavailable',response.data,route)
                self.assertNotIn(b'could not complete',response.data,route)
            guest=hotel.save_guest(['Limited Test','9891111002',None,'Indore','Madhya Pradesh','Test','L1'])
            cin=(date.today()+timedelta(days=2800)).isoformat()
            cout=(date.today()+timedelta(days=2802)).isoformat()
            limited=hotel.connection();cursor=limited.cursor()
            try:
                cursor.callproc('book_room',(guest,898,cin,cout));limited.commit()
            finally:cursor.close();limited.close()
            reservation=self.query('SELECT reservation_id FROM Reservation WHERE guest_id=%s',(guest,))[0]['reservation_id']
            payment=hotel.execute("INSERT INTO Payment(reservation_id,amount,payment_date,mode) VALUES(%s,10,%s,'Cash')",(reservation,cin))
            hotel.execute('DELETE FROM Payment WHERE payment_id=%s',(payment,))
            hotel.execute('DELETE FROM Reservation WHERE reservation_id=%s',(reservation,))
            hotel.execute('DELETE FROM Guest WHERE guest_id=%s',(guest,))
            for forbidden in ['CREATE TABLE should_be_denied(id INT)', 'DROP TABLE Payment','SELECT * FROM mysql.user']:
                with self.assertRaises(Error,msg=forbidden):hotel.execute(forbidden)
        finally:
            hotel.DB_CONFIG=original
            cur.execute(f"DROP USER IF EXISTS '{username}'@'localhost'")
            cur.close();admin.close()

    def test_integrity_upgrade_preserves_existing_bcnf_data(self):
        import uuid
        database='hotel_upgrade_'+uuid.uuid4().hex[:12]
        conn=mysql.connector.connect(**CONFIG)
        cur=conn.cursor()
        try:
            run_script(conn,(ROOT/'tests/fixtures/bcnf_schema.sql').read_text(),database)
            run_script(conn,(ROOT/'data.sql').read_text(),database)
            before={}
            for table in ['Hotel','Location','Guest','RoomType','Room','Reservation','Payment']:
                cur.execute(f'SELECT * FROM {table} ORDER BY 1');before[table]=cur.fetchall()
            run_script(conn,(ROOT/'migrations/002_database_integrity.sql').read_text(),database)
            run_script(conn,(ROOT/'advanced.sql').read_text(),database)
            for table,rows in before.items():
                cur.execute(f'SELECT * FROM {table} ORDER BY 1');self.assertEqual(cur.fetchall(),rows,table)
            with self.assertRaises(Error):cur.execute("UPDATE Guest SET phone='bad' WHERE guest_id=1")
            conn.rollback()
        finally:
            cur.execute(f'DROP DATABASE IF EXISTS `{database}`');cur.close();conn.close()


    def test_parallel_reservation_updates_cannot_overlap(self):
        cin=(date.today()+timedelta(days=2900)).isoformat()
        cout=(date.today()+timedelta(days=2902)).isoformat()
        ids=[hotel.execute("INSERT INTO Reservation(guest_id,room_id,check_in,check_out,status) VALUES(%s,897,%s,%s,'Cancelled')",(guest,cin,cout)) for guest in [1,2]]
        barrier=threading.Barrier(2)
        def activate(reservation):
            conn=mysql.connector.connect(**CONFIG,database=self.db)
            cur=conn.cursor();cur.execute('SET SESSION innodb_lock_wait_timeout=3')
            barrier.wait(timeout=5)
            try:
                cur.execute("UPDATE Reservation SET status='Booked' WHERE reservation_id=%s",(reservation,))
                conn.commit();return True
            except Error:
                conn.rollback();return False
            finally:cur.close();conn.close()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(activate,reservation) for reservation in ids]
                self.assertEqual(sum(f.result(timeout=10) for f in futures),1)
        finally:
            hotel.execute('DELETE FROM Reservation WHERE reservation_id IN (%s,%s)',tuple(ids))

    def test_parallel_maintenance_and_booking_are_consistent(self):
        cin=(date.today()+timedelta(days=3000)).isoformat()
        cout=(date.today()+timedelta(days=3002)).isoformat()
        barrier=threading.Barrier(2)
        def mutate(maintenance):
            conn=mysql.connector.connect(**CONFIG,database=self.db)
            cur=conn.cursor();cur.execute('SET SESSION innodb_lock_wait_timeout=3')
            conn.start_transaction(isolation_level='REPEATABLE READ')
            cur.execute('SELECT COUNT(*) FROM Reservation');cur.fetchall()
            barrier.wait(timeout=5)
            try:
                if maintenance:cur.execute("UPDATE Room SET status='Maintenance' WHERE room_id=896")
                else:cur.execute('INSERT INTO Reservation(guest_id,room_id,check_in,check_out) VALUES(1,896,%s,%s)',(cin,cout))
                conn.commit();return True
            except Error:
                conn.rollback();return False
            finally:cur.close();conn.close()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(mutate,maintenance) for maintenance in [True,False]]
                self.assertEqual(sum(f.result(timeout=10) for f in futures),1)
            status=self.query('SELECT status FROM Room WHERE room_id=896')[0]['status']
            count=self.query('SELECT COUNT(*) n FROM Reservation WHERE room_id=896 AND check_in=%s',(cin,))[0]['n']
            self.assertIn((status,count),[('Maintenance',0),('Available',1)])
        finally:
            hotel.execute('DELETE FROM Reservation WHERE room_id=896 AND check_in=%s',(cin,))
            hotel.execute("UPDATE Room SET status='Available' WHERE room_id=896")

    def test_admin_setup_stores_hash_and_preserves_existing_secret(self):
        import tempfile
        from unittest.mock import patch
        from contextlib import redirect_stdout
        from io import StringIO
        from dotenv import dotenv_values
        from werkzeug.security import check_password_hash
        import configure_admin
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'.env.example').write_text((ROOT/'.env.example').read_text())
            password='test-only-long-admin-password'
            output=StringIO()
            with patch.object(configure_admin,'__file__',str(root/'configure_admin.py')), patch.object(configure_admin,'getpass',side_effect=[password,password]), redirect_stdout(output):
                configure_admin.main()
            values=dotenv_values(root/'.env')
            self.assertTrue(check_password_hash(values['ADMIN_PASSWORD_HASH'],password))
            self.assertNotIn(password,(root/'.env').read_text())
            self.assertNotIn(password,output.getvalue())
            self.assertEqual(len(values['SECRET_KEY']),64)
            if __import__('os').name=='posix':self.assertEqual((root/'.env').stat().st_mode & 0o777,0o600)
            with patch.object(configure_admin,'__file__',str(root/'configure_admin.py')), patch.object(configure_admin,'getpass',side_effect=[password,password]), redirect_stdout(StringIO()):
                configure_admin.main()
            self.assertEqual(dotenv_values(root/'.env')['SECRET_KEY'],values['SECRET_KEY'])


if __name__=='__main__':
    import unittest
    unittest.main()
