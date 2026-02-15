from pymongo import MongoClient


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
            )
            self.db = self.client_mongo[self.mongo_database]
        except Exception as e:
            print(f"Failed to connect to MongoDB: {e}")
            self.client_mongo = None

    def disconnect(self):
        """Close MongoDB connection."""
        if self.client_mongo:
            self.client_mongo.close()
            print("Disconnected from MongoDB")

    def insert_data(self, collection_name, data) :
        """Insert data into a collection."""
        if not self.db:
            print("Error: Not connected to MongoDB")
            return False
        try:
            collection = self.db[collection_name]
            result = collection.insert_one(data)
            return True
        except Exception as e:
            print(f"Error inserting data: {e}")
            return False

    def health_check(self):
        """
        This fuction checks if the MongoDB connection is alive by sending a ping command.
        Returns: True if the connection is healthy, False otherwise.

        """

        try:
            if self.client_mongo:
                self.client_mongo.admin.command('ping')
                return True
            return False
        except Exception as e:
            print(f"Database health check failed: {e}")
            return False
