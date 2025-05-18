# biometric_data_service.py
import os
import time
import datetime
import logging
from dotenv import load_dotenv
from garminconnect import Garmin
import psycopg2
from psycopg2.extras import execute_values
import schedule
import json
from typing import Dict, Any, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('BiometricDataService')

# Constants
AVAILABLE_METHODS = {
    "get_steps_data": "steps",
    "get_stats": "stats",
    "get_heart_rates": "heart_rate",
    "get_hrv_data": "hrv",
    "get_stress_data": "stress",
    "get_sleep_data": "sleep",
    "get_rhr_day": "resting_hr",
    "get_respiration_data": "respiration",
    "get_intensity_minutes_data": "intensity_minutes",
    "get_body_battery": "body_battery",
    "get_spo2_data": "spo2",
    "get_max_metrics": "max_metrics",
    "get_fitnessage_data": "fitness_age",
    "get_floors": "floors",
}

class BiometricDataService:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Garmin Connect credentials
        self.email = os.getenv("GARMIN_EMAIL")
        self.password = os.getenv("GARMIN_PASSWORD")
        
        # Database connection parameters
        self.timescale_conn_params = {
            "dbname": os.getenv("TIMESCALE_DB_NAME", "biometric_data"),
            "user": os.getenv("TIMESCALE_DB_USER", "postgres"),
            "password": os.getenv("TIMESCALE_DB_PASSWORD", "postgres"),
            "host": os.getenv("TIMESCALE_DB_HOST", "localhost"),
            "port": os.getenv("TIMESCALE_DB_PORT", "5432")
        }
        
        # PostgreSQL connection parameters for analytics results
        self.postgres_conn_params = {
            "dbname": os.getenv("POSTGRES_DB_NAME", "analytics_data"),
            "user": os.getenv("POSTGRES_DB_USER", "postgres"),
            "password": os.getenv("POSTGRES_DB_PASSWORD", "postgres"),
            "host": os.getenv("POSTGRES_DB_HOST", "localhost"),
            "port": os.getenv("POSTGRES_DB_PORT", "5432")
        }
        
        # Initialize Garmin client
        self.client = None
        
        # Initialize database connections
        self.timescale_conn = None
        
        # Set schedule parameters
        self.fetch_interval_hours = int(os.getenv("FETCH_INTERVAL_HOURS", "1"))
        self.days_to_fetch = int(os.getenv("DAYS_TO_FETCH", "7"))
        
        # Initialize system
        self._initialize_system()
        
    def _initialize_system(self):
        """Initialize system components and setup tables"""
        try:
            # Initialize TimescaleDB connection
            self._setup_timescale_db()
            
            # Initialize Garmin client
            self._login_to_garmin()
            
            logger.info("System initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize system: {e}")
            raise
    
    def _setup_timescale_db(self):
        """Connect to TimescaleDB and set up necessary tables"""
        try:
            # Connect to TimescaleDB
            self.timescale_conn = psycopg2.connect(**self.timescale_conn_params)
            
            # Create tables if they don't exist
            with self.timescale_conn.cursor() as cursor:
                # Create users table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create biometric_data hypertable
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS biometric_data (
                        id SERIAL,
                        user_id INTEGER NOT NULL,
                        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                        data_type VARCHAR(50) NOT NULL,
                        metric_name VARCHAR(100) NOT NULL,
                        value JSONB,
                        raw_data JSONB,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (id, timestamp),
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        UNIQUE (user_id, timestamp, data_type, metric_name)
                    )
                """)
                
                # Check if the table is already a hypertable to avoid errors
                try:
                    cursor.execute("""
                        SELECT * FROM _timescaledb_catalog.hypertable 
                        WHERE table_name = 'biometric_data'
                    """)
                    is_hypertable = cursor.fetchone() is not None
                except Exception as e:
                    logger.warning(f"Failed to check if table is a hypertable: {e}")
                    is_hypertable = False  # Assume it's not a hypertable
                
                if not is_hypertable:
                    # Convert to TimescaleDB hypertable
                    try:
                        cursor.execute("""
                            SELECT create_hypertable('biometric_data', 'timestamp')
                        """)
                    except Exception as e:
                        logger.warning(f"Failed to create hypertable: {e}")
                        # Continue execution anyway
                
                # Create index for faster queries
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_biometric_user_type_time 
                    ON biometric_data (user_id, data_type, timestamp DESC)
                """)
                
                # Ensure the current user exists
                cursor.execute("""
                    INSERT INTO users (email) 
                    VALUES (%s) 
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id
                """, (self.email,))
                
                result = cursor.fetchone()
                if result:
                    self.user_id = result[0]
                else:
                    cursor.execute("SELECT id FROM users WHERE email = %s", (self.email,))
                    self.user_id = cursor.fetchone()[0]
                
                self.timescale_conn.commit()
                
            logger.info("TimescaleDB setup complete")
        except Exception as e:
            logger.error(f"Failed to setup TimescaleDB: {e}")
            if self.timescale_conn:
                self.timescale_conn.close()
            raise
    
    def _login_to_garmin(self):
        """Login to Garmin Connect API"""
        try:
            if not self.email or not self.password:
                raise ValueError("Missing Garmin Connect credentials")
            
            self.client = Garmin(self.email, self.password)
            self.client.login()
            logger.info("Logged in to Garmin Connect")
        except Exception as e:
            logger.error(f"Failed to login to Garmin Connect: {e}")
            raise
    
    def _safe_call(self, method_name, date):
        """Safely call Garmin API method"""
        if not self.client:
            self._login_to_garmin()
            
        if hasattr(self.client, method_name):
            method = getattr(self.client, method_name)
            try:
                result = method(date)
                if result:
                    logger.info(f"Method {method_name} for {date} returned data: {type(result)}")
                    if isinstance(result, dict):
                        logger.info(f"Dict keys: {result.keys()}")
                    elif isinstance(result, list):
                        logger.info(f"List length: {len(result)}")
                else:
                    logger.warning(f"Method {method_name} for {date} returned no data (None or empty)")
                return result
            except Exception as e:
                logger.error(f"Error calling {method_name}: {e}")
                # Attempt to re-login if there's an authentication error
                if "authentication" in str(e).lower() or "login" in str(e).lower():
                    logger.info("Attempting to re-login to Garmin Connect")
                    self._login_to_garmin()
                    # Retry once after re-login
                    method = getattr(self.client, method_name)
                    try:
                        return method(date)
                    except Exception as retry_err:
                        logger.error(f"Error on retry for {method_name}: {retry_err}")
                return None
        else:
            logger.warning(f"Method {method_name} not found in Garmin client")
            return None
    
    def _flatten_data(self, data, prefix=""):
        """Flatten nested data structure for storage"""
        result = {}
        if isinstance(data, dict):
            for key, value in data.items():
                new_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, (dict, list)):
                    result.update(self._flatten_data(value, new_key))
                else:
                    result[new_key] = value
        elif isinstance(data, list):
            for i, item in enumerate(data):
                new_key = f"{prefix}[{i}]"
                if isinstance(item, (dict, list)):
                    result.update(self._flatten_data(item, new_key))
                else:
                    result[new_key] = item
        return result
    
    def _save_to_timescale(self, user_id, date, data_type, data):
        """Save data to TimescaleDB"""
        try:
            if not self.timescale_conn or self.timescale_conn.closed:
                logger.info("Reconnecting to TimescaleDB as connection was closed")
                self._setup_timescale_db()
                
            with self.timescale_conn.cursor() as cursor:
                rows = []
                timestamp = datetime.datetime.fromisoformat(date)
                
                # Handle different data structure types
                if isinstance(data, dict):
                    # If it's a simple dictionary, save each key as a metric
                    flattened_data = self._flatten_data(data)
                    logger.debug(f"Flattened data contains {len(flattened_data)} metrics")
                    for metric_name, value in flattened_data.items():
                        # Convert value to JSON if it's a complex type
                        if isinstance(value, (dict, list)):
                            json_value = json.dumps(value)
                        else:
                            json_value = value
                        
                        rows.append((
                            user_id,
                            timestamp,
                            data_type,
                            metric_name,
                            json_value,
                            json.dumps(data)
                        ))
                else:
                    # If it's another type, save it as a single metric
                    # Convert to JSON string if it's a complex type
                    if isinstance(data, (dict, list)):
                        json_value = json.dumps(data)
                    else:
                        json_value = data
                        
                    rows.append((
                        user_id,
                        timestamp,
                        data_type,
                        "value",
                        json_value,
                        json.dumps(data) if isinstance(data, (dict, list)) else None
                    ))
                
                if rows:
                    logger.info(f"Inserting {len(rows)} rows for {data_type} data")
                    # Insert data into biometric_data table
                    try:
                        execute_values(
                            cursor,
                            """
                            INSERT INTO biometric_data 
                            (user_id, timestamp, data_type, metric_name, value, raw_data)
                            VALUES %s
                            ON CONFLICT (user_id, timestamp, data_type, metric_name) DO UPDATE
                            SET value = EXCLUDED.value, 
                                raw_data = EXCLUDED.raw_data,
                                created_at = CURRENT_TIMESTAMP
                            """,
                            rows
                        )
                        
                        self.timescale_conn.commit()
                        logger.info(f"Successfully committed {len(rows)} rows for {data_type}")
                    except Exception as insert_error:
                        logger.error(f"Insert error for {data_type}: {insert_error}")
                        self.timescale_conn.rollback()
                        return False
                else:
                    logger.warning(f"No rows to insert for {data_type}")
                    
                return True
        except Exception as e:
            logger.error(f"Failed to save {data_type} data: {e}")
            if self.timescale_conn and not self.timescale_conn.closed:
                self.timescale_conn.rollback()
            return False
    
    def fetch_and_store_data(self, days_back=1):
        """Fetch data from Garmin and store in TimescaleDB"""
        try:
            today = datetime.date.today()
            date_range = [today - datetime.timedelta(days=i) for i in range(days_back)]
            
            stored_data_count = 0
            for date in date_range:
                logger.info(f"Fetching data for {date.isoformat()}")
                date_str = date.isoformat()
                
                for method_name, data_type in AVAILABLE_METHODS.items():
                    result = self._safe_call(method_name, date)
                    if result is not None:
                        if self._save_to_timescale(self.user_id, date_str, data_type, result):
                            stored_data_count += 1
                
            logger.info(f"Completed fetching and storing data. Stored {stored_data_count} data points.")
            
            # Trigger analytics calculation
            self._trigger_analytics()
            
            return stored_data_count
        except Exception as e:
            logger.error(f"Error in fetch_and_store_data: {e}")
            return 0
    
    def _trigger_analytics(self):
        """Trigger analytics calculation"""
        try:
            # Connect to PostgreSQL
            conn = psycopg2.connect(**self.postgres_conn_params)
            try:
                with conn.cursor() as cursor:
                    # Insert a job into the analytics queue
                    cursor.execute("""
                        INSERT INTO analytics_jobs (user_id, status)
                        VALUES (%s, 'pending')
                    """, (self.user_id,))
                    conn.commit()
                logger.info(f"Triggered analytics calculation for user {self.user_id}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to trigger analytics: {e}")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
    
    def schedule_data_fetch(self):
        """Schedule regular data fetches"""
        # Schedule frequent fetch for recent data
        schedule.every(self.fetch_interval_hours).hours.do(
            self.fetch_and_store_data, days_back=self.days_to_fetch
        )
        
        # Also fetch immediately
        self.fetch_and_store_data(days_back=self.days_to_fetch)
        
        logger.info(f"Scheduled data fetch every {self.fetch_interval_hours} hours for the last {self.days_to_fetch} days")
        
    def run_scheduler(self):
        """Run the scheduler loop"""
        logger.info("Starting scheduler")
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

# Run the service if executed directly
if __name__ == "__main__":
    service = BiometricDataService()
    service.schedule_data_fetch()
    service.run_scheduler()
