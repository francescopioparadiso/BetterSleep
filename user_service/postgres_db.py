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
            raise SystemExit(1)
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
        # 1. Check if an invitation already exists for this house and email
        existing_invite = self._execute_query(
            "SELECT 1 FROM invitations WHERE house_id = %s AND email = %s",
            (i['house_id'], i['email']),
            fetch=True, single=True
        )
        if existing_invite:
            return None

        # 2. Check if the user is already a member of this house
        # First, find the user_id for the given email
        user = self._execute_query(
            "SELECT id FROM users WHERE email = %s",
            (i['email'],),
            fetch=True, single=True
        )
        
        if user:
            existing_member = self._execute_query(
                "SELECT 1 FROM house_members WHERE house_id = %s AND user_id = %s",
                (i['house_id'], user['id']),
                fetch=True, single=True
            )
            if existing_member:
                return None

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
        result = self._execute_query(query, (r['house_id'], r.get('user_id'), r['name']), fetch=True, single=True)
        return result['id'] if result else None

    def assign_room(self, room_id, user_id):
        query = "UPDATE rooms SET user_id = %s WHERE id = %s AND user_id IS NULL"
        return self._execute_query(query, (user_id, room_id))

    def unassign_room(self, room_id, user_id):
        query = "UPDATE rooms SET user_id = NULL WHERE id = %s AND user_id = %s"
        return self._execute_query(query, (room_id, user_id))

    def unassign_user_from_house_rooms(self, user_id, house_id):
        query = "UPDATE rooms SET user_id = NULL WHERE house_id = %s AND user_id = %s"
        return self._execute_query(query, (house_id, user_id))

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

    def get_user_room_info(self, user_id):
        """Get the room and house information for a user."""
        query = """
            SELECT r.id as room_id, r.house_id, r.name as room_name
            FROM rooms r
            WHERE r.user_id = %s
            LIMIT 1
        """
        return self._execute_query(query, (user_id,), fetch=True, single=True)

    def get_room_info(self, room_id):
        """Get room information including house_id and user_id."""
        query = "SELECT id, house_id, user_id, name FROM rooms WHERE id = %s"
        return self._execute_query(query, (room_id,), fetch=True, single=True)


    def update_user_preferences(self, user):
        """Update user preferences and return the changed fields."""
        changed_fields = {}

        if 'night_time' in user:
            changed_fields['night_time'] = user['night_time']
        if 'morning_time' in user:
            changed_fields['morning_time'] = user['morning_time']

        if not changed_fields:
            return None

        # Build dynamic update query
        fields = []
        values = []
        for field, value in changed_fields.items():
            fields.append(f"{field} = %s")
            values.append(value)

        query = f"UPDATE users SET {', '.join(fields)} WHERE id = %s"
        values.append(user['id'])

        success = self._execute_query(query, tuple(values))
        return changed_fields if success else None
    def update_room_preferences(self, room):
        # Build dynamic query with only provided fields
        fields = []
        values = []

        if 'temperature_night' in room:
            fields.append("temperature_night = %s")
            values.append(room['temperature_night'])
        if 'temperature_morning' in room:
            fields.append("temperature_morning = %s")
            values.append(room['temperature_morning'])
        if 'light_night' in room:
            fields.append("light_night = %s")
            values.append(room['light_night'])
        if 'light_morning' in room:
            fields.append("light_morning = %s")
            values.append(room['light_morning'])

        if not fields:
            return False

        query = f"UPDATE rooms SET {', '.join(fields)} WHERE id = %s"
        values.append(room['id'])

        return self._execute_query(query, tuple(values))

    def get_user_room_preferences(self, bedroom_id):
        """Get user and room preferences separately for two-level caching.
        """
        query = "SELECT temperature_night, temperature_morning, light_night, light_morning, user_id, house_id FROM rooms WHERE id = %s"
        result1 = self._execute_query(query, (bedroom_id,), fetch=True, single=True)

        if not result1:
            logger.warning(f"Room {bedroom_id} not found")
            return None

        if not result1.get('user_id'):
            logger.warning(f"Room {bedroom_id} has no assigned user")
            return None

        query2 = "SELECT night_time, morning_time FROM users WHERE id = %s"
        result2 = self._execute_query(query2, (result1['user_id'],), fetch=True, single=True)

        if not result2:
            logger.warning(f"User {result1['user_id']} not found")
            return None

        # Separate user and room preferences for two-level caching
        preferences = {
            'user_preferences': {
                'user_id': result1['user_id'],
                'night_time': result2['night_time'],
                'morning_time': result2['morning_time'],
                'room_id': bedroom_id,
                'house_id': result1['house_id'],
                'temperature_night': result1['temperature_night'],
                'temperature_morning': result1['temperature_morning'],
                'light_night': result1['light_night'],
                'light_morning': result1['light_morning']
            }
        }
        return preferences


    def get_all_active_rooms_with_user(self):
        """Get all rooms that have an assigned user, along with their preferences."""
        query = """
            SELECT user_id, id from rooms
            WHERE user_id IS NOT NULL AND active = TRUE
        """
        result= self._execute_query(query, fetch=True)
        active_rooms = dict()
        for room in result:
            active_rooms[room['user_id']] = room['id']

        return active_rooms

    def deactivate_user_rooms(self, user_id):
        """Deactivate all rooms for a user across all houses."""
        query = "UPDATE rooms SET active = FALSE WHERE user_id = %s"
        return self._execute_query(query, (user_id,))

    def set_room_active(self, room_id, user_id):
        """Set a room as active for a user (verify user is assigned to room)."""
        query = "UPDATE rooms SET active = TRUE WHERE id = %s AND user_id = %s"
        return self._execute_query(query, (room_id, user_id))

    def get_active_room(self, user_id):
        """Get the currently active room for a user."""
        query = "SELECT * FROM rooms WHERE user_id = %s AND active = TRUE LIMIT 1"
        return self._execute_query(query, (user_id,), fetch=True, single=True)