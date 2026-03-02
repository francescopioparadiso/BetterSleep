import logging
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
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
            logger.debug(f"Service last_update value: {service.get('last_update')} (type: {type(service.get('last_update')).__name__})")

            # Add insertion timestamp if not present
            if 'inserted_at' not in service:
                service['inserted_at'] = datetime.now(timezone.utc)

            result = self.db.services.insert_one(service)
            logger.info(f"Service {service['serviceID']} inserted successfully with ID: {result.inserted_id}")
            logger.debug(f"Service data saved - last_update: {service.get('last_update')}, inserted_at: {service.get('inserted_at')}")
            return True
        except DuplicateKeyError:
            logger.warning(f"Service ID {service['serviceID']} already exists")
            return False
        except Exception as e:
            logger.error(f"Error inserting service: {e}", exc_info=True)
            raise

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
            logger.debug(f"Updating service {service_id} last_update to: {last_update} (type: {type(last_update).__name__})")

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
            # Forza la conversione a stringa per evitare mismatch
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

    def delete_stale_services(self, ttl_seconds):
        try:
            # 1️⃣ Calcola cutoff
            cutoff_time = datetime.now() - timedelta(seconds=ttl_seconds)

            # 2️⃣ Usa lo STESSO formato salvato nel DB
            cutoff_str = cutoff_time.strftime("%Y-%m-%d %H:%M:%S")

            logger.debug(
                f"Cleanup: current_time={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, "
                f"cutoff_time={cutoff_str}, ttl_seconds={ttl_seconds}"
            )

            # 3️⃣ Confronto stringa ISO-like ordinabile
            result = self.db.services.delete_many({
                "last_update": {"$lt": cutoff_str}
            })

            deleted_count = result.deleted_count

            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} stale services (older than {cutoff_str})")
            else:
                logger.debug(f"No stale services to delete (cutoff: {cutoff_str})")

            return deleted_count

        except Exception as e:
            logger.error(f"Error deleting stale services: {e}", exc_info=True)
            raise

# DEVICES OPERATIONS
    def insert_device(self, device):

        try:
            # Generate device_id if not provided
            if 'device_id' not in device:
                import uuid
                device['device_id'] = str(uuid.uuid4())

            if 'inserted_at' not in device:
                device['inserted_at'] = datetime.now(timezone.utc)

            result = self.db.devices.insert_one(device)
            logger.info(f"Device {device['device_id']} inserted successfully")
            return device['device_id']
        except Exception as e:
            logger.error(f"Error inserting device: {e}")
            return None

    def update_device(self, device):

        try:
            device_id = device.get('device_id')
            if not device_id:
                raise ValueError("device_id is required for update")

            result = self.db.devices.update_one(
                {"device_id": device_id},
                {"$set": device}
            )
            if result.matched_count > 0:
                logger.info(f"Device {device_id} updated successfully")
                return True
            logger.warning(f"Device {device_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error updating device: {e}")
            raise

    def delete_device(self, device_id):

        try:
            result = self.db.devices.delete_one({"device_id": device_id})
            if result.deleted_count > 0:
                logger.info(f"Device {device_id} deleted successfully")
                return True
            logger.warning(f"Device {device_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error deleting device: {e}")
            raise

    def get_devices_by_bedroom(self, bedroom_id):

        try:
            devices = list(self.db.devices.find({"bedroom_id": bedroom_id}))
            result = []
            for device in devices:
                result.append((
                    device.get('device_id'),
                    device.get('device_name'),
                    device.get('device_type'),
                    device.get('value')
                ))
            return result
        except Exception as e:
            logger.error(f"Error retrieving devices for bedroom {bedroom_id}: {e}")
            raise


    def get_endpoint_server_database(self):

        try:
            return f"{self.host}:{self.port}"
        except Exception as e:
            logger.error(f"Error retrieving database endpoint: {e}")
            return None

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

