import logging
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure, OperationFailure

# Configure logging
logger = logging.getLogger(__name__)


class TimeSeriesDB:
    """Handles all MongoDB operations for time series data."""

    def __init__(self, config):
        self.mongo_port = config['timeSeriesDB']['port']
        self.mongo_host = config['timeSeriesDB']['host']
        self.mongo_password = config['timeSeriesDB']['password']
        self.mongo_username = config['timeSeriesDB']['username']
        self.mongo_database = config['timeSeriesDB']['database']
        self.client_mongo = None
        self.db = None
        self.connect()

    def connect(self):
        """Connect to MongoDB."""
        try:
            self.client_mongo = MongoClient(
                host=self.mongo_host,
                port=self.mongo_port,
                username=self.mongo_username,
                password=self.mongo_password,
                serverSelectionTimeoutMS=5000
            )
            self.db = self.client_mongo[self.mongo_database]
            logger.info("Successfully connected to MongoDB")
        except ServerSelectionTimeoutError as e:
            logger.error(f"Failed to connect to MongoDB - timeout: {e}")
            self.client_mongo = None
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB - connection failure: {e}")
            self.client_mongo = None
        except Exception as e:
            logger.error(f"Unexpected error connecting to MongoDB: {e}")
            self.client_mongo = None

    def disconnect(self):
        """Close MongoDB connection."""
        try:
            if self.client_mongo:
                self.client_mongo.close()
                logger.info("Disconnected from MongoDB")
        except Exception as e:
            logger.error(f"Error disconnecting from MongoDB: {e}")

    def insert_data(self, collection_name, data):
        """Insert data into a collection."""
        if not self.db:
            logger.error("Not connected to MongoDB, cannot insert data")
            return False
        try:
            collection = self.db[collection_name]
            result = collection.insert_one(data)
            logger.debug(f"Data inserted successfully with ID: {result.inserted_id}")
            return True
        except OperationFailure as e:
            logger.error(f"MongoDB operation failure during insert: {e}")
            return False
        except Exception as e:
            logger.error(f"Error inserting data into {collection_name}: {e}")
            return False

    def health_check(self):
        """
        This function checks if the MongoDB connection is alive by sending a ping command.
        Returns: True if the connection is healthy, False otherwise.
        """
        try:
            if self.client_mongo:
                self.client_mongo.admin.command('ping')
                logger.debug("MongoDB health check passed")
                return True
            logger.warning("MongoDB client is not connected")
            return False
        except ServerSelectionTimeoutError as e:
            logger.error(f"MongoDB health check failed - timeout: {e}")
            return False
        except ConnectionFailure as e:
            logger.error(f"MongoDB health check failed - connection failure: {e}")
            return False
        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")
            return False
