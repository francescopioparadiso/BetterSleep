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
    def get_email_by_user_id(self, user_id):
        query = "SELECT email FROM users WHERE id = %s"
        result = self._execute_query(query, (user_id,), fetch=True, single=True)
        return result['email'] if result else None


    # --- HOUSES ---


    def getHousesByUser(self, u):
        query = """
            SELECT h.* FROM houses h
            JOIN house_members hm ON h.id = hm.house_id
            WHERE hm.user_id = %s
            ORDER BY h.id
        """
        return self._execute_query(query, (u['id'],), fetch=True)

    def insert_house(self, h):
        query = "INSERT INTO houses (name) VALUES (%s) RETURNING id"
        result = self._execute_query(query, (h['name'],), fetch=True, single=True)
        return result['id'] if result else None

    def get_house(self, house_id):
        query = "SELECT * FROM houses WHERE id = %s"
        return self._execute_query(query, (house_id,), fetch=True, single=True)

    def get_all_houses(self):
        query = "SELECT * FROM houses ORDER BY id"
        return self._execute_query(query, fetch=True)

    def update_house(self, h):
        query = "UPDATE houses SET name = %s WHERE id = %s"
        return self._execute_query(query, (h['name'], h['id']))

    def delete_house(self, house_id):
        query = "DELETE FROM houses WHERE id = %s"
        return self._execute_query(query, (house_id,))

    # --- HOUSE MEMBERS ---
    def insert_house_member(self, m):
        query = "INSERT INTO house_members (house_id, user_id, role) VALUES (%s, %s, %s) RETURNING id"
        result = self._execute_query(query, (m['house_id'], m['user_id'], int(m.get('role', 0))), fetch=True, single=True)
        return result['id'] if result else None

    def get_house_member(self, member_id):
        query = "SELECT * FROM house_members WHERE id = %s"
        return self._execute_query(query, (member_id,), fetch=True, single=True)

    def get_all_house_members(self):
        query = "SELECT * FROM house_members ORDER BY id"
        return self._execute_query(query, fetch=True)

    def update_house_member(self, m):
        query = "UPDATE house_members SET house_id = %s, user_id = %s, role = %s WHERE id = %s"
        return self._execute_query(query, (m['house_id'], m['user_id'], int(m.get('role', 0)), m['id']))

    def delete_house_member(self, member_id):
        query = "DELETE FROM house_members WHERE id = %s"
        return self._execute_query(query, (member_id,))

    # --- INVITATIONS ---
    def insert_invitation(self, i):
        query = "INSERT INTO invitations (house_id, email, status) VALUES (%s, %s, %s) RETURNING id"
        result = self._execute_query(query, (i['house_id'], i['email'], i.get('status', 0)), fetch=True, single=True)
        return result['id'] if result else None

    def get_invitation(self, invitation_id):
        query = "SELECT * FROM invitations WHERE id = %s"
        return self._execute_query(query, (invitation_id,), fetch=True, single=True)

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

    def get_room(self, room_id):
        query = "SELECT * FROM rooms WHERE id = %s"
        return self._execute_query(query, (room_id,), fetch=True, single=True)

    def get_all_rooms(self):
        query = "SELECT * FROM rooms ORDER BY id"
        return self._execute_query(query, fetch=True)

    def update_room(self, r):
        query = "UPDATE rooms SET house_id = %s, user_id = %s, name = %s WHERE id = %s"
        return self._execute_query(query, (r['house_id'], r['user_id'], r['name'], r['id']))

    def delete_room(self, room_id):
        query = "DELETE FROM rooms WHERE id = %s"
        return self._execute_query(query, (room_id,))
