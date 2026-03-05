import sys
import logging
import psycopg2
from psycopg2 import DatabaseError, IntegrityError, OperationalError
from werkzeug.security import generate_password_hash, check_password_hash

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
        try:
            return psycopg2.connect(**self.db_conf)
        except OperationalError as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during database connection: {e}")
            raise

    def _execute_query(self, query, params=None, fetch=False, single=False):
        conn = None
        try:
            conn = self.connect()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    if fetch:
                        columns = [desc[0] for desc in cur.description]
                        if single:
                            row = cur.fetchone()
                            if row:
                                return dict(zip(columns, row))
                            return None
                        return [dict(zip(columns, r)) for r in cur.fetchall()]
                    return cur.rowcount > 0
        except IntegrityError as e:
            logger.error(f"Database integrity error: {e}")
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

    # --- USERS ---


    def signup_user(self, email, password, night_time=None, morning_time=None):
        # check if email already exists
        if self._execute_query("SELECT 1 FROM users WHERE email = %s", (email,), fetch=True, single=True):
            return None 
        
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        query = "INSERT INTO users (email, password, night_time, morning_time) VALUES (%s, %s, %s, %s) RETURNING id"
        result = self._execute_query(query, (email, hashed_password, night_time or '22:00', morning_time or '07:00'), fetch=True, single=True)
        return result['id'] if result else None
        
    def login_user(self, email, password):
        query = "SELECT * FROM users WHERE email = %s"
        user = self._execute_query(query, (email,), fetch=True, single=True)
        
        if user and check_password_hash(user['password'], password):
            return user
            
        return None

    def update_user(self, u):
        query = "UPDATE users SET email = %s, night_time = %s, morning_time = %s WHERE id = %s"
        return self._execute_query(query, (u['email'], u.get('night_time', '22:00'), u.get('morning_time', '07:00'), u['id']))
    def get_all_users(self):
        query = "SELECT * FROM users ORDER BY id"
        return self._execute_query(query, fetch=True)

    # --- HOUSES ---


    def insert_house(self, h):
        query = "INSERT INTO houses (name) VALUES (%s) RETURNING id"
        result = self._execute_query(query, (h['name'],), fetch=True, single=True)
        return result['id'] if result else None

    def get_all_houses(self):
        query = "SELECT * FROM houses ORDER BY id"
        return self._execute_query(query, fetch=True)

    def delete_house(self, house_id):
        query = "DELETE FROM houses WHERE id = %s"
        return self._execute_query(query, (house_id,))

    # --- HOUSE MEMBERS ---
    def insert_house_member(self, m):
        query = "INSERT INTO house_members (house_id, user_id, role) VALUES (%s, %s, %s) RETURNING id"
        result = self._execute_query(query, (m['house_id'], m['user_id'], int(m.get('role', 0))), fetch=True, single=True)
        return result['id'] if result else None

    def get_all_house_members(self):
        query = "SELECT * FROM house_members ORDER BY id"
        return self._execute_query(query, fetch=True)

    def delete_house_member(self, member_id):
        query = "DELETE FROM house_members WHERE id = %s"
        return self._execute_query(query, (member_id,))

    # --- INVITATIONS ---
    def insert_invitation(self, i):
        query = "INSERT INTO invitations (house_id, email, status) VALUES (%s, %s, %s) RETURNING id"
        result = self._execute_query(query, (i['house_id'], i['email'], i.get('status', 0)), fetch=True, single=True)
        return result['id'] if result else None

    def get_all_invitations(self):
        query = "SELECT * FROM invitations ORDER BY id"
        return self._execute_query(query, fetch=True)

    def update_invitation(self, i):
        query = "UPDATE invitations SET house_id = %s, email = %s, status = %s WHERE id = %s"
        return self._execute_query(query, (i['house_id'], i['email'], i.get('status', 0), i['id']))

    def delete_invitation(self, invitation_id):
        query = "DELETE FROM invitations WHERE id = %s"
        return self._execute_query(query, (invitation_id,))

    # --- ROOMS ---
    def insert_room(self, r):
        query = "INSERT INTO rooms (house_id, user_id, name) VALUES (%s, %s, %s) RETURNING id"
        result = self._execute_query(query, (r['house_id'], r['user_id'], r['name']), fetch=True, single=True)
        return result['id'] if result else None

    def get_all_rooms(self):
        query = "SELECT * FROM rooms ORDER BY id"
        return self._execute_query(query, fetch=True)

    def update_room(self, r):
        query = """UPDATE rooms SET 
            temperature_night = %s, temperature_morning = %s,
            light_night = %s, light_morning = %s
            WHERE id = %s"""
        return self._execute_query(query, (
            r.get('temperature_night', 18), r.get('temperature_morning', 22),
            r.get('light_night', 0), r.get('light_morning', 100),
            r['id']
        ))

    def delete_room(self, room_id):
        query = "DELETE FROM rooms WHERE id = %s"
        return self._execute_query(query, (room_id,))

    # --- SENSORS ---

    DEFAULT_SENSOR_TYPES = [
        {"type": "ambient_temp", "name": "Temperature Sensor"},
        {"type": "humidity",     "name": "Humidity Sensor"},
        {"type": "light",        "name": "Light Sensor"},
        {"type": "heart_rate",   "name": "Heart Rate Sensor"},
        {"type": "vibration",    "name": "Vibration Sensor"},
        {"type": "presence",     "name": "Presence Sensor"},
    ]

    def insert_sensor(self, room_id, sensor_type, name, mqtt_topic=None):
        query = "INSERT INTO sensors (room_id, type, name, mqtt_topic) VALUES (%s, %s, %s, %s) RETURNING id"
        result = self._execute_query(query, (room_id, sensor_type, name, mqtt_topic), fetch=True, single=True)
        return result['id'] if result else None

    def create_default_sensors(self, room_id, house_id):
        """Create all default sensors for a newly created room."""
        sensor_ids = []
        for sensor_def in self.DEFAULT_SENSOR_TYPES:
            mqtt_topic = f"House/{house_id}/Room/{room_id}/sensor/{sensor_def['type']}/data"
            sensor_id = self.insert_sensor(room_id, sensor_def['type'], sensor_def['name'], mqtt_topic)
            if sensor_id:
                sensor_ids.append(sensor_id)
        return sensor_ids

    def get_sensors_by_room(self, room_id):
        query = "SELECT * FROM sensors WHERE room_id = %s ORDER BY id"
        return self._execute_query(query, (room_id,), fetch=True)

    def delete_sensor(self, sensor_id):
        query = "DELETE FROM sensors WHERE id = %s"
        return self._execute_query(query, (sensor_id,))
