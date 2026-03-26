import json
import logging
import os

from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

def clean_database():
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        time_series_conf_path = os.path.join(base_dir, 'time_series', 'conf.json')
        
        with open(time_series_conf_path, 'r') as f:
            config = json.load(f)
        
        mongo_config = config['timeSeriesDB']
        client = MongoClient(
            host=mongo_config['host'],
            port=mongo_config['port'],
            username=mongo_config['username'],
            password=mongo_config['password'],
            serverSelectionTimeoutMS=5000
        )

        primary_db_name = mongo_config['database']
        analytics_db_name = mongo_config.get('analyticsDatabase', primary_db_name)

        cleanup_targets = {
            primary_db_name: ['measurements', 'sleep_analytics'],
            analytics_db_name: ['measurements', 'sleep_analytics'],
        }

        total_deleted = 0

        for db_name, collections in cleanup_targets.items():
            db = client[db_name]
            existing_collections = set(db.list_collection_names())

            for collection_name in collections:
                if collection_name not in existing_collections:
                    logging.info(
                        f"Skipped '{db_name}.{collection_name}' because the collection does not exist."
                    )
                    continue

                result = db[collection_name].delete_many({})
                total_deleted += result.deleted_count
                logging.info(
                    f"Deleted {result.deleted_count} documents from '{db_name}.{collection_name}'."
                )

        logging.info(
            "Successfully cleaned up MongoDB sleep analytics and sensor data "
            f"across all configured databases. Total documents deleted: {total_deleted}."
        )
        
    except Exception as e:
        logging.error(f"Error during database cleanup: {e}")

if __name__ == "__main__":
    clean_database()
