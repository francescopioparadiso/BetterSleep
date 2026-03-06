import sys
import os
# This tells Python to add the parent directory to its searchable paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import logging
import cherrypy
from postgres_db import PostgresDB
from common import catalog_client  # <--- Now this will work!

# Configure logging
logger = logging.getLogger(__name__)

# ============================================================
# CATALOG REST SERVICE
# ============================================================

class UserService:
    exposed = True
    def __init__(self, conf_user_service):
        self.catalog_url = conf_user_service['catalogURL']
        self.service_info = conf_user_service['serviceInfo']
        self.remove_interval = conf_user_service.get('removeInterval', 10)
        self.db_conf = conf_user_service['Database']
        self.db = PostgresDB(self.db_conf)
        self.catalog = catalog_client.CatalogClient(self.catalog_url, self.service_info, remove_interval=self.remove_interval)

        try:
            self.catalog.register()
        except Exception as e:
            logger.error(f'Failed to Register with Catalog: {e}')
            raise Exception

    # POST METHOD - Create new resources
    def POST(self, *uri, **params):

        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "signup": self._post_signup,   # Changed from addUser to match Swift
            "login": self._post_login,     # Moved login to POST to match Swift
            "addHouse": self._post_add_house,
            "addRoom": self._post_add_room,
            "addInvitation": self._post_add_invitation,
            "addHouseMember": self._post_add_house_member,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _post_signup(self):
        new_user = self._load_json_body()
        require_fields(new_user, ['email', 'password'])
        
        user_id = self.db.signup_user(new_user['email'], new_user['password'])
        if user_id:
            return json.dumps({"status": "success", "id": user_id, "message": "User Added"})
        raise cherrypy.HTTPError(409, "The User already exists")

    def _post_login(self):
        credentials = self._load_json_body()
        require_fields(credentials, ['email', 'password'])
        
        clean_email = credentials['email'].strip()
        
        user = self.db.login_user(clean_email, credentials['password'])
        if user:
            if 'created_at' in user and user['created_at']:
                user['created_at'] = str(user['created_at'])
                
            return json.dumps({"status": "success", "id": user['id'], "user": user})
            
        raise cherrypy.HTTPError(401, "Invalid email or password")

    def _post_add_house(self):
        """Add a new house to the catalog."""
        new_house = self._load_json_body()
        require_fields(new_house, ['name'])

        house_id = self.db.insert_house(new_house)
        if house_id:
            return json.dumps({"status": "success", "id": house_id, "message": "House Added"})
        raise cherrypy.HTTPError(409, "The House already exists")

    def _post_add_invitation(self):
        """Add a new invitation to the catalog."""
        new_invite = self._load_json_body()
        require_fields(new_invite, ['house_id', 'email'])

        invite_id = self.db.insert_invitation(new_invite)
        if invite_id:
            return json.dumps({"status": "success", "id": invite_id, "message": "Invitation Added"})
        raise cherrypy.HTTPError(409, "The Invitation already exists")

    def _post_add_house_member(self):
        """Add a new house member to the catalog."""
        new_member = self._load_json_body()
        require_fields(new_member, ['house_id', 'user_id'])

        member_id = self.db.insert_house_member(new_member)
        if member_id:
            return json.dumps({"status": "success", "id": member_id, "message": "House Member Added"})
        raise cherrypy.HTTPError(409, "The House Member already exists")
    
    def _post_add_room(self):
        """Add a new room to the catalog."""
        new_room = self._load_json_body()
        require_fields(new_room, ['house_id', 'user_id', 'name'])

        room_id = self.db.insert_room(new_room)
        if room_id:
            return json.dumps({
                "status": "success",
                "id": room_id,
                "message": "Room Added"
            })
        raise cherrypy.HTTPError(409, "The Room already exists")

    # PUT METHOD - Update existing resources
    def PUT(self, *uri, **params):
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "updateUser": self._put_update_user,
            "updateInvitation": self._put_update_invitation,
            "updateRoom": self._put_update_room,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _put_update_user(self):
        """Update an existing user in the catalog."""
        updated_user = self._load_json_body()
        require_fields(updated_user, ['id'])

        success = self.db.update_user(updated_user)
        if success:
            return json.dumps({"status": "success", "message": "User updated"})
        raise cherrypy.HTTPError(404, "User not found")

    def _put_update_invitation(self):
        """Update an existing invitation in the catalog."""
        updated_invite = self._load_json_body()
        require_fields(updated_invite, ['id'])

        success = self.db.update_invitation(updated_invite)
        if success:
            return json.dumps({"status": "success", "message": "Invitation updated"})
        raise cherrypy.HTTPError(404, "Invitation not found")

    def _put_update_room(self):
        """Update room settings (temperature/light night/morning)."""
        updated_room = self._load_json_body()
        require_fields(updated_room, ['id'])

        success = self.db.update_room(updated_room)
        if success:
            return json.dumps({"status": "success", "message": "Room updated"})
        raise cherrypy.HTTPError(404, "Room not found")

    # DELETE METHOD - Remove resources
    def DELETE(self, *uri, **params):
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "removeHouse": self._delete_remove_house,
            "removeRoom": self._delete_remove_room,
            "removeInvitation": self._delete_remove_invitation,
            "removeHouseMember": self._delete_remove_house_member,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _delete_remove_house(self, params):
        """Delete a house by ID."""
        house_id = params.get('id')
        if not house_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")

        success = self.db.delete_house(house_id)
        if success:
            return json.dumps({"status": "success", "message": "House Deleted"})
        raise cherrypy.HTTPError(404, "House not found")

    def _delete_remove_room(self, params):
        """Delete a room by ID."""
        room_id = params.get('id')
        if not room_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")

        success = self.db.delete_room(room_id)
        if success:
            return json.dumps({"status": "success", "message": "Room Deleted"})
        raise cherrypy.HTTPError(404, "Room not found")

    def _delete_remove_invitation(self, params):
        """Delete an invitation by ID."""
        invite_id = params.get('id')
        if not invite_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")

        success = self.db.delete_invitation(invite_id)
        if success:
            return json.dumps({"status": "success", "message": "Invitation Deleted"})
        raise cherrypy.HTTPError(404, "Invitation not found")

    def _delete_remove_house_member(self, params):
        """Delete a house member by ID."""
        member_id = params.get('id')
        if not member_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")

        success = self.db.delete_house_member(member_id)
        if success:
            return json.dumps({"status": "success", "message": "House Member Deleted"})
        raise cherrypy.HTTPError(404, "House Member not found")

    # --------------------------------------------------------
    # GET METHOD - Retrieve resources
    # --------------------------------------------------------
    def GET(self, *uri, **params):
        """Handle GET requests to retrieve information about Services, Devices, Users, or Bedrooms."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "getAllHouses": self._get_all_houses,
            "getAllHouseMembers": self._get_all_house_members,
            "getAllUsers": self._get_all_users,
            "getAllRooms": self._get_all_rooms,
            "getAllInvitations": self._get_all_invitations,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)
    
    def _get_all_houses(self, params):
        """Get information about all houses."""
        houses = self.db.get_all_houses()
        return json.dumps({"status": "success", "houses": houses}, default=str)

    def _get_all_invitations(self, params):
        """Get information about all invitations."""
        invitations = self.db.get_all_invitations()
        return json.dumps({"status": "success", "invitations": invitations}, default=str)

    def _get_all_house_members(self, params):
        """Get information about all house members."""
        members = self.db.get_all_house_members()
        return json.dumps({"status": "success", "house_members": members}, default=str)
    
    def _get_all_users(self, params):
        """Get information about all users."""
        users = self.db.get_all_users()
        return json.dumps({"status": "success", "users": users}, default=str)

    def _get_all_rooms(self, params):
        """Get information about all rooms."""
        rooms = self.db.get_all_rooms()
        return json.dumps({"status": "success", "rooms": rooms}, default=str)


    def _load_json_body(self):
        body = cherrypy.request.body.read()
        try:
            return json.loads(body)
        except Exception:
            raise cherrypy.HTTPError(400, "Invalid JSON format")

def require_fields(payload, required_fields):
    if not all(field in payload for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")

def json_error_page(status, message, traceback, version):
    """Override CherryPy HTTPError to return JSON instead of HTML."""
    cherrypy.response.headers["Content-Type"] = "application/json"
    try:
        status_code = int(status.split(" ")[0])
    except (ValueError, IndexError):
        status_code = 500

    return json.dumps({
        "status": status_code,
        "error": message
    })

if __name__ == "__main__":
    with open("conf.json") as f:
        full_conf = json.load(f)

    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}
    user_service = UserService(full_conf)

    cherrypy.tree.mount(user_service, '/', conf)
    cherrypy.config.update({
        'server.socket_host': full_conf['serviceInfo']['host'],
        'server.socket_port': full_conf['serviceInfo']['port'],
    })

    cherrypy.engine.subscribe('start', user_service.catalog.start_background_loop)
    cherrypy.engine.subscribe('stop', user_service.catalog.stop_background_loop)
    cherrypy.engine.subscribe('stop', user_service.catalog.unregister)
    cherrypy.engine.start()
    cherrypy.engine.block()