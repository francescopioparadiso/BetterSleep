import json
import logging
import os
import sys

# Path setups
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
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
        
        db = client[mongo_config['database']]
        
        # Delete old mqtt data (measurements)
        res1 = db['measurements'].delete_many({})
        logging.info(f"Deleted {res1.deleted_count} documents from 'measurements' collection (Night test data).")
        
        # Check if analytics database is separate
        analytics_db_name = mongo_config.get('analyticsDatabase', mongo_config['database'])
        analytics_db = client[analytics_db_name]
        
        # Delete old aggregated analytics data
        res2 = analytics_db['sleep_analytics'].delete_many({})
        logging.info(f"Deleted {res2.deleted_count} documents from 'sleep_analytics' collection (Aggregated analytics).")
        
        logging.info("Successfully cleaned up previous test cycle data.")
        
    except Exception as e:
        logging.error(f"Error during database cleanup: {e}")

if __name__ == "__main__":
    clean_database()