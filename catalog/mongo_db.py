import logging
from datetime import datetime, timezone

from pymongo import MongoClient

logger = logging.getLogger(__name__)


class MongoDBAdapter:
    """MongoDB adapter for the Catalog service."""

    def __init__(self, config):
        """Initialize MongoDB connection.

        Args:
            config: Dictionary with keys: host, port, username, password, database
        """
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 27017)
        self.username = config.get('username')
        self.password = config.get('password')
        self.database_name = config.get('database', 'catalogdb')

        # Build connection URI
        if self.username and self.password:
            uri = f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}/"
        else:
            uri = f"mongodb://{self.host}:{self.port}/"

        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            # Test connection immediately
            self.client.server_info()
            self.db = self.client[self.database_name]
            logger.info(f"MongoDB connection established to {self.host}:{self.port}/{self.database_name}")
        except Exception as e:
            logger.critical(f"FATAL: Cannot connect to MongoDB at {self.host}:{self.port} - {str(e)}")
            logger.critical("Service cannot start without MongoDB connection. Exiting...")
            raise RuntimeError(f"MongoDB connection failed: {str(e)}")



    def _delete_stale_in_collection(self, collection, cutoff_epoch, return_docs=False):
        query_numeric = {"last_update": {"$lt": cutoff_epoch}}

        stale_docs = None
        if return_docs:
            try:
                stale_docs = list(collection.find(query_numeric, {"_id": 0}))
            except Exception as e:
                logger.error(f"Error reading stale documents for publishing: {e}")
                stale_docs = []

        deleted_count = collection.delete_many(query_numeric).deleted_count
        return deleted_count, stale_docs

    # SERVICES OPERATIONS
    def insert_service(self, service):
        try:
            logger.debug(f"Attempting to insert service: {service}")
            service["serviceID"] = int(service["serviceID"])
            if "last_update" in service:
                service["last_update"] = int(service["last_update"])
            # Check for duplicate serviceID
            if self.db.services.find_one({"serviceID": service["serviceID"]}):
                logger.warning(f"Service ID {service['serviceID']} already exists (pre-check)")
                return False
            result = self.db.services.insert_one(service)
            logger.info(f"Service {service['serviceID']} inserted successfully with ID: {result.inserted_id}")
            logger.debug(f"Service data saved - last_update: {service.get('last_update')}, inserted_at: {service.get('inserted_at')}")
            return True
        except Exception as e:
            logger.error(f"Error inserting service: {e}", exc_info=True)
            return False

    def update_service(self, service):

        try:
            result = self.db.services.update_one(
                {"serviceID": service["serviceID"]},
                {"$set": service}
            )
            if result.matched_count > 0:
                logger.info(f"Service {service['serviceID']} updated successfully")
                return True
            logger.warning(f"Service {service['serviceID']} not found")
            return False
        except Exception as e:
            logger.error(f"Error updating service: {e}")
            raise

    def update_service_last_update(self, service_id, last_update):

        try:
            service_id = int(service_id)
            last_update = int(last_update)
            result = self.db.services.update_one(
                {"serviceID": service_id},
                {"$set": {"last_update": last_update}}
            )
            if result.matched_count > 0:
                logger.info(f"Service {service_id} last_update timestamp updated to {last_update}")
                return True
            logger.warning(f"Service {service_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error updating service last_update: {e}", exc_info=True)
            raise

    def delete_service(self, service_id):
        try:
            service_id = int(service_id)
            result = self.db.services.delete_one({"serviceID": service_id})
            if result.deleted_count > 0:
                logger.info(f"Service {service_id} deleted successfully")
                return True
            logger.warning(f"Service {service_id} not found for deletion")
            return False
        except Exception as e:
            logger.error(f"Error deleting service {service_id}: {e}", exc_info=True)
            return False

    def get_all_services(self):

        try:
            services = list(self.db.services.find({}))
            logger.debug(f"Retrieved {len(services)} services from database")
            return services
        except Exception as e:
            logger.error(f"Error retrieving all services: {e}")
            return []

    def delete_stale(self, ttl_seconds):
        cutoff_epoch = int(datetime.now(timezone.utc).timestamp()) - int(ttl_seconds)
        total_deleted = 0

        del_services, _ = self._delete_stale_in_collection(self.db.services, cutoff_epoch)
        total_deleted += del_services

        del_sensors, _ = self._delete_stale_in_collection(self.db.sensors, cutoff_epoch)
        total_deleted += del_sensors

        del_actuators, stale_actuators = self._delete_stale_in_collection(self.db.actuators, cutoff_epoch, return_docs=True)
        total_deleted += del_actuators

        logger.info(
            f"Deleted {total_deleted} stale services/sensors/actuators "
            f"(older than epoch={cutoff_epoch})"
        )
        return total_deleted, (stale_actuators or [])

    def get_endpoint_Time_series_DB(self):

        try:
            service = self.db.services.find_one({"type": "TimeSeriesDB"})
            if service:
                logger.info(f"TimeSeriesDB service found: {service['endpoint']}")
                return service['endpoint']
            logger.warning("No TimeSeriesDB service found")
            return None
        except Exception as e:
            logger.error(f"Error retrieving TimeSeriesDB endpoint: {e}")
            raise

    def get_endpoint_user_service(self):

        try:
            service = self.db.services.find_one({"type": "UserService"})
            if service:
                logger.info(f"UserService found: {service['endpoint']}")
                return service['endpoint']
            logger.warning("No UserService found")
            return None
        except Exception as e:
            logger.error(f"Error retrieving UserService endpoint: {e}")
            raise

    def _sensor_variants(self, value):
        variants = []
        if value is None:
            return variants

        variants.append(value)
        string_value = str(value)
        if string_value not in variants:
            variants.append(string_value)

        try:
            int_value = int(value)
            if int_value not in variants:
                variants.append(int_value)
        except (TypeError, ValueError):
            pass

        return variants

    def _build_sensor_query(self, sensor_id=None, room_id=None):
        clauses = []

        if sensor_id is not None:
            clauses.append({"$or": [{"sensorID": candidate} for candidate in self._sensor_variants(sensor_id)]})

        if room_id is not None:
            clauses.append({"$or": [{"roomID": candidate} for candidate in self._sensor_variants(room_id)]})

        if not clauses:
            return {}
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    def _format_last_update_string(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            timestamp = float(value)
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return str(value)

    def _normalize_sensor_document(self, sensor):
        normalized = dict(sensor)

        if "sensorID" in normalized and normalized["sensorID"] is not None:
            normalized["sensorID"] = str(normalized["sensorID"])
        if "roomID" in normalized and normalized["roomID"] is not None:
            normalized["roomID"] = str(normalized["roomID"])
        if "houseID" in normalized and normalized["houseID"] is not None:
            normalized["houseID"] = str(normalized["houseID"])
        if "last_update" in normalized and normalized["last_update"] is not None:
            normalized["last_update"] = self._format_last_update_string(normalized["last_update"])
        if "endpoint" not in normalized:
            normalized["endpoint"] = ""

        return normalized
    ### Actuators OPERATIONS
    def insert_sensor(self,new_sensor):
        try:
            logger.debug(f"Attempting to insert sensor: {new_sensor}")
            sensor_id = new_sensor.get("sensorID")
            room_id = new_sensor.get("roomID")


            if not sensor_id:
                logger.warning("Sensor insertion failed: missing sensorID")
                return False

            # Build query that includes room scope when available so same sensorID can exist in different rooms
            query = self._build_sensor_query(sensor_id=sensor_id, room_id=room_id)

            # Check for duplicate sensorID in the same room
            if self.db.sensors.find_one(query):
                logger.warning(f"Sensor ID {sensor_id} already exists in room {room_id} (pre-check)")
                return False

            new_sensor["sensorID"] = str(sensor_id)
            new_sensor["roomID"] = str(room_id) if room_id is not None else None
            new_sensor["houseID"] = str(new_sensor.get("houseID")) if new_sensor.get("houseID") is not None else None
            new_sensor.setdefault("endpoint", "")

            if new_sensor.get("persistent"):
                new_sensor["persistent"] = True
                new_sensor["last_update"] = self._format_last_update_string(new_sensor.get("last_update") or datetime.now().timestamp())
            elif "last_update" in new_sensor:
                new_sensor["last_update"] = int(float(new_sensor["last_update"]))

            result = self.db.sensors.insert_one(new_sensor)
            logger.info(f"Sensor {new_sensor['sensorID']} inserted successfully with ID: {result.inserted_id}")
            logger.debug(f"Sensor data saved - last_update: {new_sensor.get('last_update')}, inserted_at: {new_sensor.get('inserted_at')}")
            return True
        except Exception as e:
            logger.error(f"Error inserting sensor: {e}", exc_info=True)
            return False
    def delete_sensor(self, sensor_id, room_id=None):

        try:
            query = self._build_sensor_query(sensor_id=sensor_id, room_id=room_id)
            result = self.db.sensors.delete_one(query)
            if result.deleted_count > 0:
                logger.info(f"Sensor {sensor_id} deleted successfully (room={room_id})")
                return True
            logger.warning(f"Sensor {sensor_id} not found for deletion (room={room_id})")
            return False
        except Exception as e:
            logger.error(f"Error deleting sensor {sensor_id}: {e}", exc_info=True)
            return False

    def delete_sensors_by_room(self, room_id):
        try:
            query = {"$or": [{"roomID": candidate} for candidate in self._sensor_variants(room_id)]}
            result = self.db.sensors.delete_many(query)
            logger.info(f"Deleted {result.deleted_count} sensors for room {room_id}")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting sensors for room {room_id}: {e}", exc_info=True)
            return 0
    def update_sensor_last_update(self, sensor_id, last_update):

        try:
            query = {"$or": [{"sensorID": candidate} for candidate in self._sensor_variants(sensor_id)]}
            existing = self.db.sensors.find_one(query)
            if not existing:
                logger.warning(f"Sensor {sensor_id} not found")
                return False

            stored_last_update = (
                self._format_last_update_string(last_update)
                if existing.get("persistent")
                else int(float(last_update))
            )
            logger.debug(
                f"Updating sensor {sensor_id} last_update to: {stored_last_update} "
                f"(type: {type(stored_last_update).__name__})"
            )

            result = self.db.sensors.update_one(
                {"_id": existing["_id"]},
                {"$set": {"last_update": stored_last_update}}
            )
            if result.matched_count > 0:
                logger.info(f"Sensor {sensor_id} last_update timestamp updated to {stored_last_update}")
                return True
            logger.warning(f"Sensor {sensor_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error updating sensor last_update: {e}", exc_info=True)
            raise

    def insert_actuator(self,new_actuator):
        try:
            logger.debug(f"Attempting to insert actuator: {new_actuator}")
            # Determine actuator id key (support both ActuatorID and actuatorID payloads)
            actuator_id = None
            if new_actuator.get("ActuatorID") is not None:
                actuator_id = int(new_actuator.get("ActuatorID"))
                id_key = "ActuatorID"
            elif new_actuator.get("actuatorID") is not None:
                actuator_id = int(new_actuator.get("actuatorID"))
                id_key = "actuatorID"
            else:
                logger.warning("Actuator insertion failed: missing ActuatorID/actuatorID")
                return False

            room_id = new_actuator.get("roomID") or new_actuator.get("room_id")

            # Build query that includes room scope when available
            query = {id_key: actuator_id}
            if room_id:
                query["roomID"] = room_id

            # Check for duplicate ActuatorID in the same room
            if self.db.actuators.find_one(query):
                logger.warning(f"Actuator ID {actuator_id} already exists in room {room_id} (pre-check)")
                return False

            # Ensure payload has consistent key format: keep original key but normalize stored value to string
            new_actuator[id_key] = actuator_id
            new_actuator["roomID"] = int(room_id) if room_id is not None else None
            new_actuator["houseID"] = int(new_actuator.get("houseID")) if new_actuator.get("houseID") is not None else None

            if "last_update" in new_actuator:
                new_actuator["last_update"] = int(new_actuator["last_update"])
            result = self.db.actuators.insert_one(new_actuator)
            logger.info(f"Actuator {actuator_id} inserted successfully with ID: {result.inserted_id}")
            logger.debug(f"Actuator data saved - last_update: {new_actuator.get('last_update')}, inserted_at: {new_actuator.get('inserted_at')}")
            return True
        except Exception as e:
            logger.error(f"Error inserting actuator: {e}", exc_info=True)
            return False
    def delete_actuator(self, actuator_id, room_id=None):

        try:
            actuator_id = int(actuator_id)

            # Try ActuatorID key first
            query = {"ActuatorID": actuator_id}
            if room_id:
                query["roomID"] = room_id
            doc = self.db.actuators.find_one(query, {"_id": 0})
            result = self.db.actuators.delete_one(query)
            if result.deleted_count == 0:
                # Fall back to lowercase key
                query = {"actuatorID": actuator_id}
                if room_id:
                    query["roomID"] = room_id
                doc = self.db.actuators.find_one(query, {"_id": 0})
                result = self.db.actuators.delete_one(query)

            if result.deleted_count > 0:
                logger.info(f"Actuator {actuator_id} deleted successfully (room={room_id})")
                return True, (doc or {})

            logger.warning(f"Actuator {actuator_id} not found for deletion (room={room_id})")
            return False, None
        except Exception as e:
            logger.error(f"Error deleting actuator {actuator_id}: {e}", exc_info=True)
            return False, None
    def update_actuator_last_update(self, actuator_id, last_update):

        try:
            actuator_id = int(actuator_id)
            last_update = int(last_update)
            logger.debug(f"Updating actuator {actuator_id} last_update to: {last_update} (type: {type(last_update).__name__})")

            # Try both possible field names when building the query
            query = {"ActuatorID": actuator_id}
            result = self.db.actuators.update_one(
                query,
                {"$set": {"last_update": last_update}}
            )
            if result.matched_count > 0:
                logger.info(f"Actuator {actuator_id} last_update timestamp updated to {last_update}")
                return True
            # Fall back to lower-case query
            query = {"actuatorID": actuator_id}
            result = self.db.actuators.update_one(
                query,
                {"$set": {"last_update": last_update}}
            )
            if result.matched_count > 0:
                logger.info(f"Actuator {actuator_id} last_update timestamp updated to {last_update} with lowercase key")
                return True
            logger.warning(f"Actuator {actuator_id} not found for last_update update")
            return False
        except Exception as e:
            logger.error(f"Error updating actuator last_update: {e}", exc_info=True)
            raise

    def get_sensor_by_room (self, room_id):
        try:
            sensors = [
                self._normalize_sensor_document(sensor)
                for sensor in self.db.sensors.find(
                    {"$or": [{"roomID": candidate} for candidate in self._sensor_variants(room_id)]}
                )
            ]
            logger.debug(f"Retrieved {len(sensors)} sensors for room {room_id} from database")
            return sensors
        except Exception as e:
            logger.error(f"Error retrieving sensors for room {room_id}: {e}")
            return []

    def get_actuator_by_room(self, room_id):
        try:
            try:
                room_key = int(room_id)
            except Exception:
                room_key = room_id

            actuators = list(self.db.actuators.find(
                {"roomID": room_key},
                {"_id": 0}  # exclude MongoDB _id
            ))
            logger.debug(f"Retrieved {len(actuators)} actuators for room {room_id} from database")
            return actuators
        except Exception as e:
            logger.error(f"Error retrieving actuators for room {room_id}: {e}")
            return []

    def close(self):
        """Close the database connection."""
        try:
            self.client.close()
            logger.info("MongoDB connection closed")
        except Exception as e:
            logger.error(f"Error closing MongoDB connection: {e}")
