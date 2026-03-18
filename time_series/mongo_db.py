import logging
from pymongo import MongoClient

logger = logging.getLogger(__name__)


def _get_senml_aggregation(filter_query, start_time=None, end_time=None):
    """
    Convert the query into a MongoDB pipeline that produces SenML format.
    Each output document is a single SenML object
    """
    pipeline = [
        {"$match": filter_query},
        {
            "$project": {
                "_id": 0,
                "bn": {
                    "$concat": [
                        {"$toString": "$house_id"}, ":",
                        {"$toString": "$room_id"}, ":",
                        {"$toString": "$sensor_id"}, ":",
                        {"$toString": "$sensor_type"}
                    ]
                },
                "e": "$e"
            }
        },
        # One document per event
        {"$unwind": {"path": "$e", "preserveNullAndEmptyArrays": False}},
        # Drop events without a timestamp
        {"$match": {"e.t": {"$exists": True}}},
    ]
    #Time filter for the "getSensorDataByRoomAndTimeRange" endpoint
    if start_time is not None and end_time is not None:
        pipeline.append({"$match": {"e.t": {"$gte": start_time, "$lte": end_time}}})

    pipeline += [
        # Chronological order within each sensor
        {"$sort": {"bn": 1, "e.t": 1}},
        # Collapse all events for the same sensor into ONE document
        {
            "$group": {
                "_id": "$bn",
                "e": {
                    "$push": {
                        "n": "$e.n",
                        "v": "$e.v",
                        "t": "$e.t",
                        "u": {"$ifNull": ["$e.u", None]}
                    }
                },
            }
        },
        # Final SenML shape
        {"$project": {"_id": 0, "bn": "$_id", "e": 1}}
    ]

    return pipeline


class MongoDB:
    def __init__(self, config):
        self.mongo_port = config['timeSeriesDB']['port']
        self.mongo_host = config['timeSeriesDB']['host']
        self.mongo_password = config['timeSeriesDB']['password']
        self.mongo_username = config['timeSeriesDB']['username']
        self.mongo_database = config['timeSeriesDB']['database']
        self.analytics_database = config['timeSeriesDB'].get('analyticsDatabase', self.mongo_database)
        self.client_mongo = None
        self.db = None
        self.connect()

    def connect(self):
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
        except Exception as e:
            logger.error(f"Error connecting to MongoDB: {e}")
            self.client_mongo = None
            self.db = None

    def health_check(self):
        try:
            self.client_mongo.admin.command('ping')
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    # --- QUERY EXECUTION ---

    def _execute_query_measurements(self, filter_query, start_time=None, end_time=None):
        """Run the aggregation pipeline and return a list of SenML objects.

        Each element: { "bn": "...", "e": [{n, v, t, u}, ...] }
        One element per unique sensor — all events grouped inside "e".
        """
        if self.db is None:
            return []
        try:
            collection = self.db["measurements"]
            pipeline = _get_senml_aggregation(filter_query, start_time, end_time)
            return list(collection.aggregate(pipeline))
        except Exception as e:
            logger.error(f"Aggregation error with filter {filter_query}: {e}")
            return []

    # --- PUBLIC QUERY METHODS (all return the same SenML list format) ---

    def get_sensor_by_room(self, room_id):
        return self._execute_query_measurements({"room_id": int(room_id)})

    def get_sensor_by_type(self, sensor_type):
        return self._execute_query_measurements({"sensor_type": int(sensor_type)})

    def get_sensor_by_room_and_type(self, room_id, sensor_type):
        return self._execute_query_measurements({"room_id": int(room_id), "sensor_type": int(sensor_type)})

    def get_sensor_by_id(self, sensor_id):
        return self._execute_query_measurements({"sensor_id": int(sensor_id)})

    def get_all_sensors(self):
        return self._execute_query_measurements({})

    def get_sensor_data_by_room_and_time_range(self, room_id, start_time, end_time):
        if self.db is None:
            logger.warning("Database not connected")
            return []
        return self._execute_query_measurements(
            {"room_id": int(room_id)},
            start_time=int(float(start_time)),
            end_time=int(float(end_time))
        )


    def insert_measurements_data(self, collection_name, data):
        """Insert a SenML record, splitting bn into indexed integer fields."""
        if self.db is None:
            return False
        try:
            collection = self.db[collection_name]
            document = dict(data)
            if "bn" in data:
                try:
                    # Split bn → store as integers for fast, index-friendly queries
                    # Format: "house_id:room_id:sensor_id:sensor_type"
                    # sensor_type values:
                    #   0 = ambient_temp | 1 = humidity | 2 = presence
                    #   3 = heart_rate   | 4 = vibration
                    parts = data["bn"].split(":")
                    document["house_id"] = int(parts[0])
                    document["room_id"] = int(parts[1])
                    document["sensor_id"] = int(parts[2])
                    document["sensor_type"] = int(parts[3])
                except (ValueError, IndexError):
                    logger.warning(f"Invalid bn format: {data['bn']}")

            collection.insert_one(document)
            return True
        except Exception as e:
            logger.error(f"Error inserting: {e}")
            return False

    def insert_sleep_score(self, data):
        """Insert sleep score data."""
        if self.db is None:
            return False
        try:
            collection = self.db["sleep_analytics"]
            collection.insert_one(data)
            return True
        except Exception as e:
            logger.error(f"Error inserting sleep score data: {e}")
            return False

    def get_sleep_analytics_by_user(self, user_id, limit=30):
        """Retrieve sleep analytics summaries for a user, sorted by date descending."""
        if self.db is None:
            logger.warning("Database not connected")
            return []
        try:
            collection = self.db["sleep_analytics"]
            cursor = collection.find(
                {"user_id": int(user_id)},
                {"_id": 0}
            ).sort("date", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            logger.error(f"Error retrieving sleep analytics for user {user_id}: {e}")
            return []

    def get_sleep_analytics_by_date(self, user_id, date_str):
        """Retrieve sleep analytics for a user on a specific date (YYYY-MM-DD)."""
        if self.db is None:
            logger.warning("Database not connected")
            return None
        try:
            collection = self.db["sleep_analytics"]
            result = collection.find_one(
                {"user_id": str(user_id), "date": date_str},
                {"_id": 0}
            )
            return result
        except Exception as e:
            logger.error(f"Error retrieving analytics for user {user_id} on {date_str}: {e}")
            return None

    def get_latest_sleep_analytics(self, user_id):
        """Retrieve the most recent sleep analytics summary for a user."""
        if self.db is None:
            logger.warning("Database not connected")
            return None
        try:
            collection = self.db["sleep_analytics"]
            result = collection.find_one(
                {"user_id": int(user_id)},
                {"_id": 0},
                sort=[("date", -1)]
            )
            return result
        except Exception as e:
            logger.error(f"Error retrieving latest analytics for user {user_id}: {e}")
            return None