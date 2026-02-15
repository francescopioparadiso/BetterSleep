import sys
import psycopg2


class PostgresDB:
    def __init__(self, db_conf):
        self.db_conf = db_conf
        # Quick connection test
        if not self._execute("SELECT 1"):
            print("Critical error: Unable to connect to the database.")
            sys.exit(1)
        print("PostgreSQL connection established successfully.")

    def connect(self):
        return psycopg2.connect(**self.db_conf)

    def _execute(self, query, params=None, fetch=False, single=False):
        """
        Universal method to handle DB operations.
        - If fetch=True: returns data (list of tuples or a single tuple).
        - If fetch=False: returns True if the operation affected rows, False otherwise.
        """
        conn = None
        try:
            conn = self.connect()
            with conn:  # Handles automatic COMMIT/ROLLBACK
                with conn.cursor() as cur:
                    cur.execute(query, params)

                    if fetch:
                        if single:
                            return cur.fetchone()  # Returns a tuple or None
                        return cur.fetchall()  # Returns a list of tuples

                    # For INSERT, UPDATE, DELETE: return True if at least one row was affected
                    return cur.rowcount > 0

        except Exception as e:
            print(f"Database Error: {e}")
            return None if fetch else False
        finally:
            if conn:
                conn.close()

    # --- CRUD SERVICES ---
    def insert_service(self, s):
        query = """
                INSERT INTO services (service_id, name, endpoint, timestamp, type)
                VALUES (%s, %s, %s, %s, %s) \
                """
        return self._execute(query, (s['serviceID'], s['name'], s['endpoint'], s['last_update'], s['type']))

    def update_service(self, s):
        query = """
                UPDATE services
                SET name=%s, \
                    endpoint=%s, \
                    timestamp=%s, \
                    type=%s
                WHERE service_id = %s \
                """
        return self._execute(query, (s['name'], s['endpoint'], s['last_update'], s['type'], s['serviceID']))

    def update_service_last_update(self,service_id, last_update):
        query = """
                UPDATE services
                SET timestamp=%s
                WHERE service_id = %s \
                """
        return self._execute(query, (last_update, service_id))
    def delete_service(self, service_id):
        return self._execute("DELETE FROM services WHERE service_id = %s", (service_id,))

    def delete_stale_services(self, seconds):
        query = """
                DELETE \
                FROM services
                WHERE timestamp < (NOW() - make_interval(secs => %s)) OR timestamp IS NULL \
                """
        return self._execute(query, (seconds,))

    # --- CRUD DEVICES ---
    def insert_device(self, d):
        query = """
                INSERT INTO devices (device_id, device_name, measure_types, bedroom_id)
                VALUES (%s, %s, %s, %s) \
                """
        return self._execute(query, (d['deviceID'], d['deviceName'], d['measureTypes'], d['bedroomID']))

    def update_device(self, d):
        query = """
                UPDATE devices
                SET device_name=%s, \
                    measure_types=%s, \
                    bedroom_id=%s
                WHERE device_id = %s \
                """
        return self._execute(query, (d['deviceName'], d['measureTypes'], d['bedroomID'], d['deviceID']))

    def delete_device(self, device_id):
        return self._execute("DELETE FROM devices WHERE device_id = %s", (device_id,))

    # --- CRUD USERS ---
    def insert_user(self, u):
        query = "INSERT INTO users (username, telegram_chat_id) VALUES (%s, %s)"
        return self._execute(query, (u['username'], u['telegram_chat_id']))

    def update_user(self, u):
        query = "UPDATE users SET telegram_chat_id = %s WHERE username = %s"
        return self._execute(query, (u['telegram_chat_id'], u['username']))

    # --- BEDROOMS & CHECKS ---
    def insert_bedroom(self, b):
        query = "INSERT INTO bedrooms (room_name, password) VALUES (%s, %s)"
        return self._execute(query, (b['room_name'], b['password']))

    def room_exists(self, room_id):
        query = "SELECT 1 FROM bedrooms WHERE bedroom_id = %s"
        # Returns True if a record is found, False otherwise
        result = self._execute(query, (room_id,), fetch=True, single=True)
        return result is not None

    def get_endpoint_server_database(self):
        query = "SELECT  endpoint FROM services WHERE type = 'DatabaseAdapter' LIMIT 1"
        return self._execute(query, fetch=True, single=True)