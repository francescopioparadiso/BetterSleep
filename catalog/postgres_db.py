import sys
import logging

import psycopg2
from psycopg2 import DatabaseError, IntegrityError, OperationalError

# Configure logging
logger = logging.getLogger(__name__)


class PostgresDB:
    def __init__(self, db_conf):
        self.db_conf = db_conf
        # Quick connection test
        if not self._execute_query("SELECT 1"):
            logger.critical("Unable to connect to the database.")
            sys.exit(1)
        logger.info("PostgreSQL connection established successfully.")

    def connect(self):
        """Establish a connection to the PostgreSQL database."""
        try:
            return psycopg2.connect(**self.db_conf)
        except OperationalError as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during database connection: {e}")
            raise

    def _execute_query(self, query, params=None, fetch=False, single=False):
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

        except IntegrityError as e:
            logger.error(f"Database integrity error (likely duplicate key): {e}")
            return None if fetch else False
        except OperationalError as e:
            logger.error(f"Database operational error: {e}")
            return None if fetch else False
        except DatabaseError as e:
            logger.error(f"Database error: {e}")
            return None if fetch else False
        except Exception as e:
            logger.error(f"Unexpected error during database operation: {e}")
            return None if fetch else False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    logger.warning(f"Error closing database connection: {e}")

    # --- CRUD SERVICES ---
    def insert_service(self, s):
        """Insert a new service into the database."""
        query = """
                INSERT INTO services (service_id, name, endpoint, timestamp, type)
                VALUES (%s, %s, %s, %s, %s)
                """
        return self._execute_query(query, (s['serviceID'], s['name'], s['endpoint'], s['last_update'], s['type']))

    def update_service(self, s):
        """Update an existing service in the database."""
        query = """
                UPDATE services
                SET name= %s, endpoint= %s, timestamp= %s, type= %s
                WHERE service_id = %s
                """
        return self._execute_query(query, (s['name'], s['endpoint'], s['last_update'], s['type'], s['serviceID']))

    def update_service_last_update(self, service_id, last_update):
        """Update only the timestamp of a service."""
        query = """
                UPDATE services
                SET timestamp= %s 
                WHERE service_id = %s
                """
        return self._execute_query(query, (last_update, service_id))

    def delete_service(self, service_id):
        """Delete a service by its ID."""
        return self._execute_query("DELETE FROM services WHERE service_id = %s", (service_id,))

    def delete_stale_services(self, seconds):
        """Delete services that haven't been updated within the specified seconds."""
        query = """
                DELETE FROM services
                WHERE timestamp < (NOW() - make_interval(secs => %s)) OR timestamp IS NULL
                """
        return self._execute_query(query, (seconds,))

    # --- CRUD DEVICES ---
    def insert_device(self, d):
        """Insert a new device into the database and return its generated ID."""
        # devices table: device_id INT GENERATED ALWAYS AS IDENTITY,
        # device_name VARCHAR, device_type VARCHAR, value INT, bedroom_id INT
        query = """
                INSERT INTO devices (device_name, device_type, value, bedroom_id)
                VALUES (%s, %s, %s, %s)
                RETURNING device_id
                """
        result = self._execute_query(query, (d.get('device_name'), d.get('device_type'), d.get('value', 0), d.get('bedroom_id')), fetch=True, single=True)
        return result[0] if result else None

    def update_device(self, d):
        """Update an existing device in the database."""
        query = """
                UPDATE devices
                SET device_name = %s,
                    device_type = %s,
                    value = %s,
                    bedroom_id = %s
                WHERE device_id = %s
                """
        return self._execute_query(query, (d.get('device_name'), d.get('device_type'), d.get('value', 0), d.get('bedroom_id'), d.get('device_id')))

    def delete_device(self, device_id):
        """Delete a device by its ID."""
        return self._execute_query("DELETE FROM devices WHERE device_id = %s", (device_id,))

    # --- CRUD USERS ---
    def insert_user(self, u):
        """Insert a new user into the database."""
        query = "INSERT INTO users (username, telegram_chat_id, bedroom_id) VALUES (%s, %s, %s)"
        return self._execute_query(query, (u['username'], u['telegram_chat_id'], u.get('bedroom_id')))

    def check_user_exists(self, username):
        """Check if a user exists in the database by username."""
        username = username.strip()  # rimuove spazi iniziali/finali
        logger.debug(f"Checking username: '{username}'")

        query = "SELECT 1 FROM users WHERE username = %s"
        result = self._execute_query(query, (username,), fetch=True, single=True)

        logger.debug(f"Query result: {result}")

        return result is not None

    def associete_user_to_bedroom(self, u):
        """Update an existing user in the database."""
        query = "UPDATE users SET bedroom_id = %s WHERE telegram_chat_id = %s"
        return self._execute_query(query, (u['bedroom_id'], u['telegram_chat_id']))

    def dissociete_user_from_bedroom(self, u):
        """Update an existing user in the database."""
        query = "UPDATE users SET bedroom_id = NULL WHERE telegram_chat_id = %s"
        return self._execute_query(query, (u['telegram_chat_id'],))

    def delete_user(self, username):
        """Delete a user by username."""
        return self._execute_query("DELETE FROM users WHERE username = %s", (username,))

    # --- BEDROOMS & CHECKS ---
    def insert_bedroom(self, b):
        """Insert a new bedroom and return its ID."""
        # Provide default values for Bedtime, Wakeup and Desired_Temperature
        query = """
                INSERT INTO bedrooms (room_name, Bedtime, Wakeup, Desired_Temperature)
                VALUES (%s, %s, %s, %s)
                RETURNING bedroom_id
                """
        bedtime = b.get('bedtime', '22:00:00')
        wakeup = b.get('wakeup', '07:00:00')
        desired_temp = b.get('desired_temperature', 21.0)
        # _execute deve restituire la riga con RETURNING
        result = self._execute_query(query, (b.get('room_name', 'Bedroom'), bedtime, wakeup, desired_temp), fetch=True, single=True)
        # result dovrebbe essere qualcosa come [(id,)]
        return result[0] if result else None

    def delete_bedroom(self, room_id):
        """Delete a bedroom by its ID."""
        return self._execute_query("DELETE FROM bedrooms WHERE bedroom_id = %s", (room_id,))

    def room_exists(self, room_id):
        """Check if a bedroom exists by its ID."""
        query = "SELECT 1 FROM bedrooms WHERE bedroom_id = %s"
        # Returns True if a record is found, False otherwise
        result = self._execute_query(query, (room_id,), fetch=True, single=True)
        return result is not None

    def get_endpoint_server_database(self):
        """Get the endpoint of the database service from the catalog."""
        query = "SELECT endpoint FROM services WHERE type = 'DatabaseAdapter' LIMIT 1"
        return self._execute_query(query, fetch=True, single=True)

    def getUserSession(self, chat_id):
        """Get user session (username and bedroom_id) by Telegram chat ID."""
        query = "SELECT username, bedroom_id FROM users WHERE telegram_chat_id = %s"
        return self._execute_query(query, (chat_id,), fetch=True, single=True)

    def get_devices_by_bedroom(self, bedroom_id):
        """Return a list of devices (device_id, device_name, measure_types) for a bedroom."""
        query = "SELECT device_id, device_name, device_type, value FROM devices WHERE bedroom_id = %s ORDER BY device_id"
        result = self._execute_query(query, (bedroom_id,), fetch=True, single=False)
        return result if result else []
