import json
import sys
import logging
import cherrypy
import threading
import time
from postgres_db import PostgresDB
import catalog_client
# Configure logging
logger = logging.getLogger(__name__)


# ============================================================
# CATALOG REST SERVICE
# ============================================================

class UserService:
    exposed = True
    def __init__(self, conf, cleanup_interval_s=30, service_ttl_s=60):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self.db_conf = conf['Database']
        self.db = PostgresDB(self.db_conf)
        self.catalog = catalog_client.CatalogClient(self.catalog_url, self.service_info, remove_interval=self.remove_interval)

        try:
            self.catalog.register_service()
        except Exception as e:
            logger.error(f'Failed to start catalog heartbeat: {e}')
    # --------------------------------------------------------
    # POST METHOD - Add new resources
    # --------------------------------------------------------
    def POST(self, *uri, **params):
        """Handle POST requests to add new Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "addUser": self._post_add_user,
            "addHouse": self._post_add_house,
            "addRoom": self._post_add_room,
            "addInvitation": self._post_add_invitation,
            "addHouseMember": self._post_add_house_member,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _post_add_user(self):
        """Add a new user to the catalog."""
        new_user = self._load_json_body()
        require_fields(new_user, ['email', 'password'])

        success = self.db.insert_user(new_user)
        if success:
            return json.dumps({"status": "success", "message": "User Added"})
        raise cherrypy.HTTPError(409, "The User already exists")

    def _post_add_house(self):
        """Add a new house to the catalog."""
        new_house = self._load_json_body()
        require_fields(new_house, ['name'])

        success = self.db.insert_house(new_house)
        if success:
            return json.dumps({"status": "success", "message": "House Added"})
        raise cherrypy.HTTPError(409, "The House already exists")

    def _post_add_room(self):
        """Add a new room to the catalog."""
        new_room = self._load_json_body()
        require_fields(new_room, ['house_id', 'name'])

        success = self.db.insert_room(new_room)
        if success:
            return json.dumps({"status": "success", "message": "Room Added"})
        raise cherrypy.HTTPError(409, "The Room already exists")

    def _post_add_invitation(self):
        """Add a new invitation to the catalog."""
        new_invite = self._load_json_body()
        require_fields(new_invite, ['house_id', 'email'])

        success = self.db.insert_invitation(new_invite)
        if success:
            return json.dumps({"status": "success", "message": "Invitation Added"})
        raise cherrypy.HTTPError(409, "The Invitation already exists")

    def _post_add_house_member(self):
        """Add a new house member to the catalog."""
        new_member = self._load_json_body()
        require_fields(new_member, ['house_id', 'user_id'])

        success = self.db.insert_house_member(new_member)
        if success:
            return json.dumps({"status": "success", "message": "House Member Added"})
        raise cherrypy.HTTPError(409, "The House Member already exists")

    # --------------------------------------------------------
    # PUT METHOD - Update existing resources
    # --------------------------------------------------------
    def PUT(self, *uri, **params):
        """Handle PUT requests to update Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "updateUser": self._put_update_user,
            "updateHouse": self._put_update_house,
            "updateRoom": self._put_update_room,
            "updateInvitation": self._put_update_invitation,
            "updateHouseMember": self._put_update_house_member,
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

    def _put_update_house(self):
        """Update an existing house in the catalog."""
        updated_house = self._load_json_body()
        require_fields(updated_house, ['id'])

        success = self.db.update_house(updated_house)
        if success:
            return json.dumps({"status": "success", "message": "House updated"})
        raise cherrypy.HTTPError(404, "House not found")

    def _put_update_room(self):
        """Update an existing room in the catalog."""
        updated_room = self._load_json_body()
        require_fields(updated_room, ['id'])

        success = self.db.update_room(updated_room)
        if success:
            return json.dumps({"status": "success", "message": "Room updated"})
        raise cherrypy.HTTPError(404, "Room not found")

    def _put_update_invitation(self):
        """Update an existing invitation in the catalog."""
        updated_invite = self._load_json_body()
        require_fields(updated_invite, ['id'])

        success = self.db.update_invitation(updated_invite)
        if success:
            return json.dumps({"status": "success", "message": "Invitation updated"})
        raise cherrypy.HTTPError(404, "Invitation not found")

    def _put_update_house_member(self):
        """Update an existing house member in the catalog."""
        updated_member = self._load_json_body()
        require_fields(updated_member, ['id'])

        success = self.db.update_house_member(updated_member)
        if success:
            return json.dumps({"status": "success", "message": "House Member updated"})
        raise cherrypy.HTTPError(404, "House Member not found")

    # --------------------------------------------------------
    # DELETE METHOD - Remove resources
    # --------------------------------------------------------
    def DELETE(self, *uri, **params):
        """Handle DELETE requests to remove Services, Devices, Users, or Bedrooms."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "removeUser": self._delete_remove_user,
            "removeHouse": self._delete_remove_house,
            "removeRoom": self._delete_remove_room,
            "removeInvitation": self._delete_remove_invitation,
            "removeHouseMember": self._delete_remove_house_member,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _delete_remove_user(self, params):
        """Delete a user by ID."""
        user_id = params.get('id')
        if not user_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")

        success = self.db.delete_user(user_id)
        if success:
            return json.dumps({"status": "success", "message": "User Deleted"})
        raise cherrypy.HTTPError(404, "User not found")

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
            "getUser": self._get_user,
            "getHouse": self._get_house,
            "getRoom": self._get_room,
            "getInvitation": self._get_invitation,
            "getHouseMember": self._get_house_member,
            "getAllUsers": self._get_all_users,
            "getAllHouses": self._get_all_houses,
            "getAllRooms": self._get_all_rooms,
            "getAllInvitations": self._get_all_invitations,
            "getAllHouseMembers": self._get_all_house_members,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _get_user(self, params):
        """Get information about a user by ID."""
        user_id = params.get('id')
        if not user_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")
        user = self.db.get_user(user_id)
        if user:
            return json.dumps({"status": "success", "user": user})
        raise cherrypy.HTTPError(404, "User not found")

    def _get_house(self, params):
        """Get information about a house by ID."""
        house_id = params.get('id')
        if not house_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")
        house = self.db.get_house(house_id)
        if house:
            return json.dumps({"status": "success", "house": house})
        raise cherrypy.HTTPError(404, "House not found")

    def _get_room(self, params):
        """Get information about a room by ID."""
        room_id = params.get('id')
        if not room_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")
        room = self.db.get_room(room_id)
        if room:
            return json.dumps({"status": "success", "room": room})
        raise cherrypy.HTTPError(404, "Room not found")

    def _get_invitation(self, params):
        """Get information about an invitation by ID."""
        invite_id = params.get('id')
        if not invite_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")
        invite = self.db.get_invitation(invite_id)
        if invite:
            return json.dumps({"status": "success", "invitation": invite})
        raise cherrypy.HTTPError(404, "Invitation not found")

    def _get_house_member(self, params):
        """Get information about a house member by ID."""
        member_id = params.get('id')
        if not member_id:
            raise cherrypy.HTTPError(400, "Missing 'id' parameter")
        member = self.db.get_house_member(member_id)
        if member:
            return json.dumps({"status": "success", "house_member": member})
        raise cherrypy.HTTPError(404, "House Member not found")

    def _get_all_users(self, params):
        """Get information about all users."""
        users = self.db.get_all_users()
        return json.dumps({"status": "success", "users": users})

    def _get_all_houses(self, params):
        """Get information about all houses."""
        houses = self.db.get_all_houses()
        return json.dumps({"status": "success", "houses": houses})

    def _get_all_rooms(self, params):
        """Get information about all rooms."""
        rooms = self.db.get_all_rooms()
        return json.dumps({"status": "success", "rooms": rooms})

    def _get_all_invitations(self, params):
        """Get information about all invitations."""
        invitations = self.db.get_all_invitations()
        return json.dumps({"status": "success", "invitations": invitations})

    def _get_all_house_members(self, params):
        """Get information about all house members."""
        members = self.db.get_all_house_members()
        return json.dumps({"status": "success", "house_members": members})

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

    cherrypy.engine.subscribe('start', user_service.catalog.start_background_loop())
    cherrypy.engine.subscribe('stop',  user_service.catalog.stop_background_loop())

    cherrypy.engine.start()
    cherrypy.engine.block()