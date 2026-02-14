import sys
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

class PostgresDB:
    def __init__(self, db_conf):
        self.db_conf = db_conf
        # Quick connection test
        if not self._execute("SELECT 1"):
            print("Critical error: Unable to connect to the database.")
            sys.exit(1)
        print("PostgreSQL connection successful.")

    def connect(self):
        return psycopg2.connect(**self.db_conf)

    def _execute(self, query, params=None):
        """
        Private helper method that handles opening, closing,
        committing and rolling back. Returns True if successful.
        """
        conn = None
        try:
            conn = self.connect()
            # 'with conn' handles automatic commit if everything goes well,
            # or rollback if there's an error.
            with conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    if cur.description is not None:
                        return True
                    return cur.rowcount > 0
        except psycopg2.IntegrityError:
            print("Error: Duplicate key or constraint violation.")
            return False
        except Exception as e:
            print(f"Generic SQL error: {e}")
            return False
        finally:
            if conn: conn.close()

    def _execute_rowcount(self, query, params=None):
        """
        Private helper method that returns the number of affected rows.
        """
        conn = None
        try:
            conn = self.connect()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return cur.rowcount
        except Exception as e:
            print(f"Generic SQL error: {e}")
            return 0
        finally:
            if conn: conn.close()

    def insert_service(self, s):
        query = """
            INSERT INTO services (service_id, name, endpoint, timestamp)
            VALUES (%s, %s, %s, %s)
        """
        # Just one line to execute everything!
        return self._execute(query, (s['serviceID'], s['name'],s['endpoint'] ,s['last_update']))

    def update_service(self, s):
        query = """
            UPDATE services
            SET name = %s, endpoint = %s, timestamp = %s
            WHERE service_id = %s
        """
        return self._execute(query, ( s['name'],s['endpoint'] ,s['last_update'],s['serviceID']))
    def delete_service(self, service_id):
        query = "DELETE FROM services WHERE service_id = %s"
        return self._execute(query, (service_id,))

    def delete_stale_services(self, tot):
        query = """
                DELETE \
                FROM services
                WHERE timestamp < (NOW() - make_interval(secs => %s))
                   OR timestamp IS NULL;
                """
        # Assicurati che 'tot' sia il numero di secondi (es. 60)
        return self._execute_rowcount(query, (tot,))

    def insert_device(self, d):
        query = """
            INSERT INTO devices (device_id, device_name, measure_types,bedroom_id)
            VALUES (%s, %s, %s, %s)
        """
        return self._execute(query, (d['deviceID'], d['deviceName'], d['measureTypes'], d['bedroomID']))

    def update_device(self, d):
        query = """
            UPDATE devices
            SET device_name = %s, measure_types = %s, bedroom_id = %s
            WHERE device_id = %s
        """
        return self._execute(query, (d['deviceName'], d['measureTypes'], d['bedroomID'], d['deviceID']))

    def delete_device(self, device_id):
        query = "DELETE FROM devices WHERE device_id = %s"
        return self._execute(query, (device_id,))

    def insert_user(self, u):
        query = """
            INSERT INTO users (username, telegram_chat_id)
            VALUES (%s, %s)
        """
        return self._execute(query, (u['username'], u['telegram_chat_id']))

    def update_user(self, u):
        query = """
            UPDATE users
            SET telegram_chat_id = %s
            WHERE username = %s
        """
        return self._execute(query, (u['telegram_chat_id'], u['username']))

    def delete_user(self, username):
        query = "DELETE FROM users WHERE username = %s"
        return self._execute(query, (username,))