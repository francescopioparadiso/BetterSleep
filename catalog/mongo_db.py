import logging
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

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


# SERVICES OPERATIONS
    def insert_service(self, service):
        try:
            logger.debug(f"Attempting to insert service: {service}")
            service["serviceID"] = str(service["serviceID"])
            # Forza il formato della data
            if "last_update" in service:
                try:
                    service["last_update"] = datetime.strptime(service["last_update"], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    try:
                        service["last_update"] = datetime.fromisoformat(service["last_update"]).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        service["last_update"] = str(service["last_update"])
            # Check for duplicate serviceID
            if self.db.services.find_one({"serviceID": service["serviceID"]}):
                logger.warning(f"Service ID {service['serviceID']} already exists (pre-check)")
                return False
            # Add insertion timestamp if not present
            if 'inserted_at' not in service:
                service['inserted_at'] = datetime.now(timezone.utc)
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
            service_id = str(service_id)
            # Forza il formato della data
            if isinstance(last_update, str):
                try:
                    # Prova a convertire, se già nel formato va bene
                    datetime.strptime(last_update, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # Se non è nel formato, prova a convertirlo
                    try:
                        last_update = datetime.fromisoformat(last_update).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        last_update = str(last_update)
            else:
                last_update = str(last_update)
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
            # Ensure service_id is always a string for query
            service_id = str(service_id)
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
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
        cutoff_str = cutoff_time.strftime("%Y-%m-%d %H:%M:%S")
        total_deleted = 0
        # Elimina servizi
        result_services = self.db.services.delete_many({"last_update": {"$lt": cutoff_str}})
        total_deleted += result_services.deleted_count
        # Elimina sensori (skip persistent ones)
        result_sensors = self.db.sensors.delete_many({"last_update": {"$lt": cutoff_str}, "persistent": {"$ne": True}})
        total_deleted += result_sensors.deleted_count
        # Elimina attuatori (skip persistent ones)
        result_actuators = self.db.actuators.delete_many({"last_update": {"$lt": cutoff_str}, "persistent": {"$ne": True}})
        total_deleted += result_actuators.deleted_count
        logger.info(f"Deleted {total_deleted} stale services/sensors/actuators (older than {cutoff_str})")
        return total_deleted

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
    ### Actuators OPERATIONS
    def insert_sensor(self,new_sensor):
        try:
            logger.debug(f"Attempting to insert sensor: {new_sensor}")
            # Check for duplicate sensorID
            if self.db.sensors.find_one({"sensorID": new_sensor["sensorID"]}):
                logger.warning(f"Sensor ID {new_sensor['sensorID']} already exists (pre-check)")
                return False
            result = self.db.sensors.insert_one(new_sensor)
            logger.info(f"Sensor {new_sensor['sensorID']} inserted successfully with ID: {result.inserted_id}")
            logger.debug(f"Sensor data saved - last_update: {new_sensor.get('last_update')}, inserted_at: {new_sensor.get('inserted_at')}")
            return True
        except Exception as e:
            logger.error(f"Error inserting sensor: {e}", exc_info=True)
            return False
    def delete_sensor(self, sensor_id):

        try:
            # Forza la conversione a stringa per evitare mismatch
            sensor_id = str(sensor_id)
            result = self.db.sensors.delete_one({"sensorID": sensor_id})
            if result.deleted_count > 0:
                logger.info(f"Sensor {sensor_id} deleted successfully")
                return True
            logger.warning(f"Sensor {sensor_id} not found for deletion")
            return False
        except Exception as e:
            logger.error(f"Error deleting sensor {sensor_id}: {e}", exc_info=True)
            return False
    def update_sensor_last_update(self, sensor_id, last_update):

        try:
            logger.debug(f"Updating sensor {sensor_id} last_update to: {last_update} (type: {type(last_update).__name__})")

            result = self.db.sensors.update_one(
                {"sensorID": sensor_id},
                {"$set": {"last_update": last_update}}
            )
            if result.matched_count > 0:
                logger.info(f"Sensor {sensor_id} last_update timestamp updated to {last_update}")
                return True
            logger.warning(f"Sensor {sensor_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error updating sensor last_update: {e}", exc_info=True)
            raise

    def insert_actuator(self,new_actuator):
        try:
            logger.debug(f"Attempting to insert actuator: {new_actuator}")
            # Check for duplicate actuatorID
            if self.db.actuators.find_one({"actuatorID": new_actuator["actuatorID"]}):
                logger.warning(f"Actuator ID {new_actuator['actuatorID']} already exists (pre-check)")
                return False
            result = self.db.actuators.insert_one(new_actuator)
            logger.info(f"Actuator {new_actuator['actuatorID']} inserted successfully with ID: {result.inserted_id}")
            logger.debug(f"Actuator data saved - last_update: {new_actuator.get('last_update')}, inserted_at: {new_actuator.get('inserted_at')}")
            return True
        except Exception as e:
            logger.error(f"Error inserting actuator: {e}", exc_info=True)
            return False
    def delete_actuator(self, actuator_id):

        try:
            # Forza la conversione a stringa per evitare mismatch
            actuator_id = str(actuator_id)
            result = self.db.actuators.delete_one({"actuatorID": actuator_id})
            if result.deleted_count > 0:
                logger.info(f"Actuator {actuator_id} deleted successfully")
                return True
            logger.warning(f"Actuator {actuator_id} not found for deletion")
            return False
        except Exception as e:
            logger.error(f"Error deleting actuator {actuator_id}: {e}", exc_info=True)
            return False
    def update_actuator_last_update(self, actuator_id, last_update):

        try:
            logger.debug(f"Updating actuator {actuator_id} last_update to: {last_update} (type: {type(last_update).__name__})")

            result = self.db.actuators.update_one(
                {"actuatorID": actuator_id},
                {"$set": {"last_update": last_update}}
            )
            if result.matched_count > 0:
                logger.info(f"Actuator {actuator_id} last_update timestamp updated to {last_update}")
                return True
            logger.warning(f"Actuator {actuator_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error updating actuator last_update: {e}", exc_info=True)
            raise

    def get_sensor_by_room (self, room_id):
        try:
            sensors = list(self.db.sensors.find({"roomID": room_id}))
            logger.debug(f"Retrieved {len(sensors)} sensors for room {room_id} from database")
            return sensors
        except Exception as e:
            logger.error(f"Error retrieving sensors for room {room_id}: {e}")
            return []
    # ================================================================
    # CONNECTION MANAGEMENT
    # ================================================================

    def close(self):
        """Close the database connection."""
        try:
            self.client.close()
            logger.info("MongoDB connection closed")
        except Exception as e:
            logger.error(f"Error closing MongoDB connection: {e}")
