import os
from common.common import load_json_body, json_error_page, init_mqtt_helper
import json
import logging
import cherrypy
from postgres_db import PostgresDB
from common import catalog_client
logger = logging.getLogger(__name__)

class UserService:
    exposed = True
    def __init__(self, conf_user_service):
        self.catalog_url = conf_user_service['catalogURL']
        self.service_info = conf_user_service['serviceInfo']
        self.remove_interval = conf_user_service.get('removeInterval', 10)
        self.db_conf = conf_user_service['Database']
        self.db = PostgresDB(self.db_conf)
        self.catalog = catalog_client.CatalogClient(self.catalog_url, self.service_info, remove_interval=self.remove_interval)
        self.MQTT_info = conf_user_service['MQTT']
        self.mqtt_client_publish=None
        self.topic_publish=self.MQTT_info.get('topic_publish', [])
        self.init_mqtt_client()

        try:
            self.catalog.register()
        except Exception as e:
            logger.error(f'Failed to Register with Catalog: {e}')
            raise Exception

    def init_mqtt_client(self):
        try:
            self.mqtt_client_publish = init_mqtt_helper(self, self.MQTT_info, logger)
            if self.mqtt_client_publish is None:
                self.catalog.unregister()
                raise SystemExit(1)
        except Exception as e:
            logger.error(f"Error initializing MQTT client: {e}")
            self.catalog.unregister()
            raise SystemExit(1)

    def startClient(self):
        self.mqtt_client_publish.start()

    def stopClient(self):
        self.mqtt_client_publish.stop()


    def publish(self, topic, message):
        if self.mqtt_client_publish:
            self.mqtt_client_publish.publish(topic, message)
        else:
            logger.error("MQTT client not initialized, cannot publish message")



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
        new_user = load_json_body()
        require_fields(new_user, ['email', 'password'])
        
        user_id = self.db.signup_user(new_user['email'], new_user['password'])
        if user_id:
            return json.dumps({"status": "success", "id": user_id, "message": "User Added"})
        raise cherrypy.HTTPError(409, "The User already exists")

    def _post_login(self):
        credentials = load_json_body()
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
        new_house = load_json_body()
        require_fields(new_house, ['name'])

        house_id = self.db.insert_house(new_house)
        if house_id:
            return json.dumps({"status": "success", "id": house_id, "message": "House Added"})
        raise cherrypy.HTTPError(409, "The House already exists")

    def _post_add_invitation(self):
        """Add a new invitation to the catalog."""
        new_invite = load_json_body()
        require_fields(new_invite, ['house_id', 'email'])

        invite_id = self.db.insert_invitation(new_invite)
        if invite_id:
            return json.dumps({"status": "success", "id": invite_id, "message": "Invitation Added"})
        raise cherrypy.HTTPError(409, "The Invitation already exists")

    def _post_add_house_member(self):
        """Add a new house member to the catalog."""
        new_member = load_json_body()
        require_fields(new_member, ['house_id', 'user_id'])

        member_id = self.db.insert_house_member(new_member)
        if member_id:
            return json.dumps({"status": "success", "id": member_id, "message": "House Member Added"})
        raise cherrypy.HTTPError(409, "The House Member already exists")
    
    def _post_add_room(self):
        """Add a new room to the catalog."""
        new_room = load_json_body()
        require_fields(new_room, ['house_id', 'name'])

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
            "assignRoom": self._put_assign_room,
            "unassignRoom": self._put_unassign_room,
            "setActiveRoom": self._put_set_active_room,
            "updateUserPreferences": self._put_update_user_preferences,
            "updateRoomPreferences": self._put_update_room_preferences,

        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _put_update_user(self):
        """Update an existing user in the catalog."""
        updated_user = load_json_body()
        require_fields(updated_user, ['id'])

        success = self.db.update_user(updated_user)
        if success:
            return json.dumps({"status": "success", "message": "User updated"})
        raise cherrypy.HTTPError(404, "User not found")
    def _put_update_user_preferences(self):
        """Update user preferences and notify sleep cycle manager."""
        updated_preferences = load_json_body()
        require_fields(updated_preferences, ['user_id'])

        user_id = updated_preferences['user_id']
        logger.info(f"Updating preferences for user {user_id}: {updated_preferences}")

        # Returns only the changed preferences
        changed_preferences = self.db.update_user_preferences(updated_preferences)

        if changed_preferences:
            logger.info(f"Successfully updated preferences for user {user_id}")

            # Publish MQTT message for user cache invalidation
            # User preferences are global (not tied to a specific room)
            topic = self.topic_publish[1].replace("{userID}", str(user_id))
            message = json.dumps(changed_preferences)

            try:
                self.publish(topic, message)
                logger.info(f"Published user preference change to {topic}: {message}")
            except Exception as e:
                logger.error(f"Failed to publish user preference change: {e}")

            return json.dumps({"status": "success", "message": "User preferences updated"})
        raise cherrypy.HTTPError(404, "User not found")
    def _put_update_room_preferences(self):
        """Update room preferences in the catalog."""
        updated_preferences = load_json_body()
        require_fields(updated_preferences, ['room_id'])

        room_id = updated_preferences['room_id']
        logger.info(f"Updating preferences for room {room_id}: {updated_preferences}")

        # Returns only the changed preferences
        changed_preferences = self.db.update_room_preferences(updated_preferences)

        if changed_preferences:
            logger.info(f"Successfully updated preferences for room {room_id}")

            # Get the room information for MQTT publishing
            room_info = self.db.get_room_info(room_id)
            if room_info:
                house_id = room_info['house_id']
                user_id = room_info.get('user_id')

                if user_id:
                    # Publish MQTT message for cache invalidation
                    # Topic: UserService/ChangePreference/House/{houseID}/Bedroom/{bedroomID}/User/{userID}/Preference/
                    topic = self.topic_publish[0].replace("{houseID}", str(house_id)).replace("{bedroomID}", str(room_id)).replace("{userID}", str(user_id))
                    message = json.dumps(changed_preferences)

                    try:
                        self.publish(topic, message)
                        logger.info(f"Published room preference change to {topic}: {message}")
                    except Exception as e:
                        logger.error(f"Failed to publish room preference change: {e}")
                else:
                    logger.warning(f"Room {room_id} has no assigned user, skipping MQTT publish")
            else:
                logger.warning(f"Room {room_id} not found, skipping MQTT publish")

            return json.dumps({"status": "success", "message": "Room preferences updated"})
        raise cherrypy.HTTPError(404, "Room not found")

    def _put_update_invitation(self):
        """Update an existing invitation in the catalog."""
        updated_invite = load_json_body()
        require_fields(updated_invite, ['id'])

        success = self.db.update_invitation(updated_invite)
        if success:
            return json.dumps({"status": "success", "message": "Invitation updated"})
        raise cherrypy.HTTPError(404, "Invitation not found")

    def _put_update_room(self):
        """Update room settings (temperature/light night/morning)."""
        updated_room = load_json_body()
        require_fields(updated_room, ['id'])

        success = self.db.update_room(updated_room)
        if success:
            return json.dumps({"status": "success", "message": "Room updated"})
        raise cherrypy.HTTPError(404, "Room not found")

    def _put_assign_room(self):
        """Assign the current user to a room, unassigning them from any other room in the same house."""
        body = load_json_body()
        require_fields(body, ['room_id', 'user_id', 'house_id'])

        # First unassign user from all rooms in this house
        self.db.unassign_user_from_house_rooms(body['user_id'], body['house_id'])
        # Then assign to the requested room
        success = self.db.assign_room(body['room_id'], body['user_id'])
        if success:
            return json.dumps({"status": "success", "message": "Room assigned"})
        raise cherrypy.HTTPError(404, "Room not found")

    def _put_unassign_room(self):
        """Unassign a user from a room (only the assigned user can do this)."""
        body = load_json_body()
        require_fields(body, ['room_id', 'user_id'])

        success = self.db.unassign_room(body['room_id'], body['user_id'])
        if success:
            return json.dumps({"status": "success", "message": "Room unassigned"})
        raise cherrypy.HTTPError(403, "Only the assigned user can unassign from this room")

    def _put_set_active_room(self):
        """Set a room as active for a user, or deactivate all rooms if active=false."""
        body = load_json_body()
        require_fields(body, ['room_id', 'user_id'])

        room_id = body['room_id']
        user_id = body['user_id']
        active = body.get('active', True)  # Default to True if not specified

        if active:
            logger.info(f"Setting room {room_id} as active for user {user_id}")
            # First deactivate all other rooms for this user across all houses
            self.db.deactivate_user_rooms(user_id)

            # Then activate the requested room
            success = self.db.set_room_active(room_id, user_id)
            if success:
                logger.info(f"Room {room_id} is now active for user {user_id}")
                return json.dumps({"status": "success", "message": "Room set as active"})
            raise cherrypy.HTTPError(404, "Room not found or not assigned to user")
        else:
            logger.info(f"Deactivating all rooms for user {user_id}")
            self.db.deactivate_user_rooms(user_id)
            return json.dumps({"status": "success", "message": "All rooms deactivated for user"})

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
            "getRoomById": self._get_room_by_id,
            "getUserRoomPreferences": self._get_user_room_preferences,
            "getActiveRoom": self._get_active_room,
            "getActiveRoomsWithUser": self._get_all_active_room_associeted_user,
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

    def _get_room_by_id(self, params):
        """Get room information by room id."""
        room_id = params.get('room_id') or params.get('id')
        if not room_id:
            raise cherrypy.HTTPError(400, "Missing 'room_id' parameter")

        room = self.db.get_room_info(room_id)
        if room:
            return json.dumps(room, default=str)
        raise cherrypy.HTTPError(404, "Room not found")

    def _get_all_rooms(self, params):
        """Get information about all rooms."""
        rooms = self.db.get_all_rooms()
        return json.dumps({"status": "success", "rooms": rooms}, default=str)

    def _get_user_room_preferences(self, params):
        """Get merged user+room preferences for a user (or for a bedroom, for backward compatibility)."""
        user_id = params.get('user_id')
        bedroom_id = params.get('bedroom_id')

        if user_id:
            active_room = self.db.get_active_room(user_id)
            if not active_room:
                raise cherrypy.HTTPError(404, "Active room not found for user")
            bedroom_id = active_room.get('id')

        if not bedroom_id:
            raise cherrypy.HTTPError(400, "Missing 'user_id' or 'bedroom_id' parameter")

        preferences = self.db.get_user_room_preferences(bedroom_id)
        if not preferences:
            raise cherrypy.HTTPError(404, "User or room not found")

        # Flatten legacy nested payload shape.
        merged_preferences = preferences.get('user_preferences', preferences)
        return json.dumps({"status": "success", "preferences": merged_preferences}, default=str)

    def _get_active_room(self, params):
        """Get the currently active room for a user."""
        user_id = params.get('user_id')
        if not user_id:
            raise cherrypy.HTTPError(400, "Missing 'user_id' parameter")
        
        active_room = self.db.get_active_room(user_id)
        if active_room:
            return json.dumps({"status": "success", "active_room": active_room}, default=str)
        return json.dumps({"status": "success", "active_room": None}, default=str)
    
    
    def _get_all_active_room_associeted_user(self, params):
        """Get all active rooms with the associated user information."""
        active_rooms = self.db.get_all_active_rooms_with_user()
        return json.dumps({"status": "success", "active_rooms": active_rooms}, default=str)



def require_fields(payload, required_fields):
    if not all(field in payload for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")


if __name__ == "__main__":
    with open("conf.json") as f:
        full_conf = json.load(f)

    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}
    user_service = UserService(full_conf)

    cherrypy.tree.mount(user_service, '/', conf)
    cherrypy.config.update({
        'server.socket_host': full_conf['serviceInfo']['host'],
        'server.socket_port': full_conf['serviceInfo']['port'],
        'error_page.default': json_error_page,
    })

    cherrypy.engine.subscribe('start', user_service.catalog.start_background_loop)
    cherrypy.engine.subscribe('stop', user_service.catalog.stop_background_loop)
    cherrypy.engine.subscribe('stop', user_service.catalog.unregister)
    cherrypy.engine.start()