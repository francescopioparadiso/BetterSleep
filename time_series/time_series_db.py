import logging
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure, OperationFailure

logger = logging.getLogger(__name__)


def _get_senml_aggregation(filter_query):
    """convert the query into a MongoDB aggregation pipeline that produces SenML format."""
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
        }
    ]
    return pipeline


class TimeSeriesDB:
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

    def health_check(self):
        try:
            self.client_mongo.admin.command('ping')
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    # --- LOGICA DI PARSING IN MONGO ---

    def _execute_query(self, filter_query):
        """Esegue l'aggregazione e restituisce la lista SenML."""
        if self.db is None:
            return []
        try:
            collection = self.db["measurements"]
            pipeline = _get_senml_aggregation(filter_query)
            # MongoDB esegue tutto il lavoro qui
            return list(collection.aggregate(pipeline))
        except Exception as e:
            logger.error(f"Aggregation error with filter {filter_query}: {e}")
            return []



    def get_sensor_by_room(self, room_id):
        return self._execute_query({"room_id": int(room_id)})

    def get_sensor_by_type(self, sensor_type):
        return self._execute_query({"sensor_type": int(sensor_type)})

    def get_sensor_by_room_and_type(self, room_id, sensor_type):
        return self._execute_query({"room_id": int(room_id), "sensor_type": int(sensor_type)})

    def get_sensor_by_id(self, sensor_id):
        return self._execute_query({"sensor_id": int(sensor_id)})

    def get_all_sensors(self):
        return self._execute_query({})

    def insert_data(self, collection_name, data):
        if self.db is None: return False
        try:
            collection = self.db[collection_name]
            document = dict(data)
            if "bn" in data:
                try:
                    # Splittiamo e salviamo come numeri per query veloci (Index-friendly)
                    parts = data["bn"].split(":")
                    document["house_id"] = int(parts[0])
                    document["room_id"] = int(parts[1])
                    document["sensor_id"] = int(parts[2])
                    document["sensor_type"] = int(parts[3])
                    # 0 ambient_temp
                    # 1 humidity
                    # 2 presence
                    # 3 heart_rate
                    # 4 vibration
                except (ValueError, IndexError):
                    logger.warning(f"Invalid bn format: {data['bn']}")

            collection.insert_one(document)
            return True
        except Exception as e:
            logger.error(f"Error inserting: {e}")
            return False


    def get_sensor_data_by_room_and_time_range(self, room_id, start_time, end_time):

        results = self._execute_query({
            "room_id": int(room_id),
            "e.t": {"$gte": start_time, "$lte": end_time}
        })

        sensors_by_type = defaultdict(list)

        for doc in results:
            sensor_type = str(doc["sensor_type"])  # stringa per JSON semplice

            for event in doc["e"]:
                if start_time <= event["t"] <= end_time:
                    sensors_by_type[sensor_type].append({
                        "timestamp": event["t"],
                        "value": event["v"],
                        "name": event["n"]
                    })

        return dict(sensors_by_type)