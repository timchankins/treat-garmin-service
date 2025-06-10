# biometric_data_service.py
import os
import re
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
        # Load environment variables (only if not already set, to prefer Docker env vars)
        load_dotenv(override=False)

        # Garmin Connect credentials
        self.email = os.getenv("GARMIN_EMAIL")
        self.password = os.getenv("GARMIN_PASSWORD")
        
        # Debug logging for credentials (without exposing the actual values)
        logger.info(f"Garmin email configured: {'Yes' if self.email else 'No'}")
        logger.info(f"Garmin password configured: {'Yes' if self.password else 'No'}")
        
        if not self.email or not self.password:
            logger.error("Missing Garmin credentials! Check GARMIN_EMAIL and GARMIN_PASSWORD environment variables.")
            logger.error(f"GARMIN_EMAIL: {'Set' if self.email else 'Not set'}")
            logger.error(f"GARMIN_PASSWORD: {'Set' if self.password else 'Not set'}")

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
        self.last_login_time = None

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
        """Login to Garmin Connect API with exponential backoff and connection reuse"""
        # Check if we have a recent login (within last 30 minutes)
        if (self.client and self.last_login_time and 
            time.time() - self.last_login_time < 1800):  # 30 minutes
            logger.info("Reusing existing Garmin Connect session")
            return
            
        # Check if we're in a rate limit cooldown period (1 hour)
        if hasattr(self, 'rate_limit_time') and self.rate_limit_time:
            time_since_rate_limit = time.time() - self.rate_limit_time
            if time_since_rate_limit < 3700:  # 1 hour + 100 seconds buffer
                remaining_time = 3700 - time_since_rate_limit
                logger.warning(f"Still in rate limit cooldown. {remaining_time/60:.1f} minutes remaining.")
                self.client = None
                return
                
        max_retries = 2  # Reduce retries to avoid triggering rate limit
        base_delay = 60   # Start with 1 minute delays
        
        for attempt in range(max_retries):
            try:
                if not self.email or not self.password:
                    raise ValueError("Missing Garmin Connect credentials")

                self.client = Garmin(self.email, self.password)
                self.client.login()
                self.last_login_time = time.time()
                # Clear any previous rate limit time on successful login
                self.rate_limit_time = None
                logger.info("Successfully logged in to Garmin Connect")
                return  # Success, exit early
                
            except Exception as e:
                logger.error(f"Failed to login to Garmin Connect (attempt {attempt + 1}/{max_retries}): {e}")
                
                # Check if it's a rate limit error (429)
                is_rate_limit = "429" in str(e) or "Too Many Requests" in str(e)
                
                if is_rate_limit:
                    # Record when we hit the rate limit
                    self.rate_limit_time = time.time()
                    logger.error("RATE LIMIT HIT! Garmin imposes 1-hour login restriction.")
                    logger.error("Service will continue running but won't attempt login for 1 hour.")
                    self.client = None
                    return  # Don't retry, don't crash - just wait it out
                
                if attempt < max_retries - 1:  # Don't delay on the last attempt for non-rate-limit errors
                    delay = base_delay * (attempt + 1)
                    logger.info(f"Waiting {delay} seconds before retry...")
                    time.sleep(delay)
                else:
                    # Final attempt failed for non-rate-limit errors
                    logger.error("All login attempts failed. Service will continue and retry later.")
                    self.client = None
                    return  # Don't crash the service

    def _safe_call(self, method_name, date):
        """Safely call Garmin API method with rate limiting"""
        # If no client available, don't spam logs - this should be caught upstream
        if not self.client:
            return None

        # Add delay between API calls to respect rate limits
        time.sleep(2)  # 2 second delay between requests

        if hasattr(self.client, method_name):
            method = getattr(self.client, method_name)
            try:
                # Use the same approach as the working script
                result = method(date)
                # Add detailed logging to track what data is being returned
                if result:
                    logger.info(f"Method {method_name} for {date} returned data of type: {type(result)}")
                    if isinstance(result, dict):
                        logger.info(f"Dict keys: {result.keys()}")
                    elif isinstance(result, list):
                        logger.info(f"List length: {len(result)}")
                else:
                    logger.warning(f"Method {method_name} for {date} returned no data (None or empty)")
                return result
            except Exception as e:
                logger.error(f"Error calling {method_name}: {e}")
                # Handle rate limiting errors
                if "429" in str(e) or "too many requests" in str(e).lower():
                    logger.warning("Rate limited, waiting 60 seconds before retry...")
                    time.sleep(60)
                    try:
                        return method(date)
                    except Exception as retry_err:
                        logger.error(f"Rate limit retry failed for {method_name}: {retry_err}")
                        return None
                # Simple retry once with re-login for authentication errors
                elif "authentication" in str(e).lower():
                    try:
                        logger.info("Attempting to re-login to Garmin Connect")
                        self._login_to_garmin()
                        # Try again after re-login with delay
                        time.sleep(2)
                        method = getattr(self.client, method_name)
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

    def normalize_key(key):
        """
        Convert camelCase to snake_case and lowercase for consistent JSON key format.

        Examples:
            heartRate -> heart_rate
            stressLevel -> stress_level
        """
        # First convert camelCase to snake_case
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', key)
        snake_case = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        return snake_case

    def normalize_json_keys(obj, normalize_fn=normalize_key):
        """
        Recursively normalize all keys in a JSON object or array.

        Args:
            obj: The JSON object or array to normalize
            normalize_fn: Function to normalize keys (default: normalize_key)

        Returns:
            New object with normalized keys
        """
        if isinstance(obj, dict):
            return {normalize_fn(k): normalize_json_keys(v, normalize_fn) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [normalize_json_keys(item, normalize_fn) for item in obj]
        else:
            return obj

    def _save_to_timescale(self, user_id, date, data_type, data):
        """
        Save data to TimescaleDB with proper time-series handling.
        """
        try:
            if not self.timescale_conn or self.timescale_conn.closed:
                logger.info("Reconnecting to TimescaleDB as connection was closed")
                self._setup_timescale_db()
                
            # Skip if no data
            if data is None:
                logger.warning(f"No data to save for {data_type} on {date}")
                return True
                
            # Base timestamp for daily summary metrics - add timezone if not present
            if 'T' in date and ('+' in date or 'Z' in date):
                # Already has time and timezone info
                timestamp = datetime.datetime.fromisoformat(date.replace('Z', '+00:00'))
            else:
                # Date only - add midnight time with timezone
                timestamp = datetime.datetime.fromisoformat(f"{date}T00:00:00+00:00")
            
            rows = []
            microsecond_offset = 0  # Track offset to ensure unique timestamps
            
            # Handle different data structure types
            if isinstance(data, dict):
                # Store the raw data
                raw_json = json.dumps(data)
                
                # First, store top-level metrics
                for key, value in data.items():
                    if not isinstance(value, (dict, list)):
                        # Store simple scalar values with normalized keys
                        try:
                            # Use camelCase as in source data
                            key_name = key
                            json_value = json.dumps({key_name: value})
                            
                            # Create unique timestamp for each metric to avoid conflicts
                            unique_timestamp = timestamp.replace(microsecond=microsecond_offset)
                            microsecond_offset = (microsecond_offset + 1) % 1000000
                            
                            rows.append((
                                user_id,
                                unique_timestamp,
                                data_type,
                                f"{data_type}.{key_name}",
                                json_value,
                                raw_json
                            ))
                        except Exception as e:
                            logger.warning(f"Error serializing {key}: {e}")
                
                # Special handling for sleep data to extract nested sleep duration fields
                if data_type == 'sleep':
                    sleep_duration_fields = ['sleepTimeSeconds', 'totalSleepTimeSeconds', 'deepSleepSeconds', 'napTimeSeconds']
                    
                    # Check for sleep duration in nested objects like dailySleepDTO
                    for key, value in data.items():
                        if isinstance(value, dict):
                            for field in sleep_duration_fields:
                                if field in value and value[field] is not None:
                                    try:
                                        json_value = json.dumps({field: value[field]})
                                        unique_timestamp = timestamp.replace(microsecond=microsecond_offset)
                                        microsecond_offset = (microsecond_offset + 1) % 1000000
                                        
                                        rows.append((
                                            user_id,
                                            unique_timestamp,
                                            data_type,
                                            f"{data_type}.{field}",
                                            json_value,
                                            raw_json
                                        ))
                                        logger.info(f"Extracted sleep field {field}: {value[field]} seconds from {key}")
                                    except Exception as e:
                                        logger.warning(f"Error extracting sleep field {field} from {key}: {e}")
                                        
                    # Also check if sleep duration fields are at the top level (in case structure varies)
                    for field in sleep_duration_fields:
                        if field in data and data[field] is not None and not isinstance(data[field], (dict, list)):
                            try:
                                json_value = json.dumps({field: data[field]})
                                unique_timestamp = timestamp.replace(microsecond=microsecond_offset)
                                microsecond_offset = (microsecond_offset + 1) % 1000000
                                
                                rows.append((
                                    user_id,
                                    unique_timestamp,
                                    data_type,
                                    f"{data_type}.{field}",
                                    json_value,
                                    raw_json
                                ))
                                logger.info(f"Extracted top-level sleep field {field}: {data[field]} seconds")
                            except Exception as e:
                                logger.warning(f"Error extracting top-level sleep field {field}: {e}")
                
                # Check for time-series data (arrays of values)
                for key, value in data.items():
                    if isinstance(value, list) and key.endswith(("Values", "ValuesArray")):
                        # Process time-series data
                        try:
                            series_name = key.replace("ValuesArray", "").replace("Values", "")
                            
                            for i, entry in enumerate(value):
                                if isinstance(entry, list) and len(entry) >= 2:
                                    # Try to interpret timestamp if present
                                    entry_time = None
                                    try:
                                        ts_value = entry[0]
                                        if isinstance(ts_value, (int, float)):
                                            if ts_value > 1000000000000:
                                                # Millisecond timestamp
                                                entry_time = datetime.datetime.fromtimestamp(ts_value / 1000.0, tz=datetime.timezone.utc)
                                            elif ts_value > 1000000000:
                                                # Second timestamp
                                                entry_time = datetime.datetime.fromtimestamp(ts_value, tz=datetime.timezone.utc)
                                        elif isinstance(ts_value, str):
                                            # Try parsing ISO format timestamp
                                            try:
                                                entry_time = datetime.datetime.fromisoformat(ts_value.replace('Z', '+00:00'))
                                            except:
                                                pass
                                    except Exception as e:
                                        logger.debug(f"Could not parse timestamp {entry[0]}: {e}")
                                    
                                    # Fall back to base timestamp with unique microsecond offset if no valid timestamp
                                    if entry_time is None:
                                        entry_time = timestamp.replace(microsecond=microsecond_offset)
                                        microsecond_offset = (microsecond_offset + 1) % 1000000
                                    
                                    # Store the entry data
                                    entry_data = {"value": entry[1:] if len(entry) > 2 else entry[1]}
                                    entry_json = json.dumps(entry_data)
                                    
                                    rows.append((
                                        user_id,
                                        entry_time,
                                        data_type,
                                        f"{data_type}.{series_name}",
                                        entry_json,
                                        raw_json
                                    ))
                            
                        except Exception as e:
                            logger.warning(f"Error processing time-series data {key}: {e}")
            
            elif isinstance(data, list):
                # Store the raw data
                raw_json = json.dumps(data)
                
                # Store the count
                count_timestamp = timestamp.replace(microsecond=microsecond_offset)
                microsecond_offset = (microsecond_offset + 1) % 1000000
                rows.append((
                    user_id,
                    count_timestamp,
                    data_type,
                    f"{data_type}.count",
                    json.dumps({"count": len(data)}),
                    raw_json
                ))
                
                # Store each item for smaller lists
                max_items = 250
                if len(data) <= max_items:
                    for i, item in enumerate(data):
                        try:
                            item_json = json.dumps(item)
                            item_timestamp = timestamp.replace(microsecond=microsecond_offset)
                            microsecond_offset = (microsecond_offset + 1) % 1000000
                            rows.append((
                                user_id,
                                item_timestamp,
                                data_type,
                                f"{data_type}.item_{i}",
                                item_json,
                                raw_json
                            ))
                        except Exception as e:
                            logger.warning(f"Error serializing list item {i}: {e}")
                else:
                    logger.info(f"List too large, skipping individual items: {len(data)} > {max_items}")
            
            else:
                # Simple scalar value
                try:
                    json_value = json.dumps({"value": data})
                    scalar_timestamp = timestamp.replace(microsecond=microsecond_offset)
                    rows.append((
                        user_id,
                        scalar_timestamp,
                        data_type,
                        f"{data_type}.value",
                        json_value,
                        json.dumps(data) if isinstance(data, (dict, list)) else None
                    ))
                except Exception as e:
                    logger.warning(f"Error serializing scalar value: {e}")
            
            # Insert the rows
            if rows:
                with self.timescale_conn.cursor() as cursor:
                    logger.info(f"Inserting {len(rows)} rows for {data_type} data")
                    try:
                        # Use execute_values for efficient batch insertion
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
                            rows,
                            page_size=500
                        )
                        
                        self.timescale_conn.commit()
                        logger.info(f"Successfully committed {len(rows)} rows for {data_type}")
                        return True
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
            # Check if we're in rate limit cooldown before doing anything
            if hasattr(self, 'rate_limit_time') and self.rate_limit_time:
                time_since_rate_limit = time.time() - self.rate_limit_time
                if time_since_rate_limit < 3700:  # 1 hour + 100 seconds buffer
                    remaining_time = 3700 - time_since_rate_limit
                    logger.info(f"Skipping data fetch - rate limit cooldown ({remaining_time/60:.1f} minutes remaining)")
                    return 0
                    
            # Try to login if needed
            if not self.client:
                self._login_to_garmin()
                
            # If still no client after login attempt, skip this fetch cycle
            if not self.client:
                logger.warning("No authenticated client available - skipping data fetch")
                return 0

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

            # Only trigger analytics if we actually stored some data
            if stored_data_count > 0:
                self._trigger_analytics()
            else:
                logger.info("No new data stored - skipping analytics calculation")

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

    def check_fetch_triggers(self):
        """Check for manual fetch triggers from the dashboard"""
        try:
            if not self.timescale_conn or self.timescale_conn.closed:
                self._setup_timescale_db()
                
            with self.timescale_conn.cursor() as cursor:
                # Check for pending fetch triggers
                cursor.execute("""
                    SELECT id, user_id, days_back 
                    FROM fetch_triggers 
                    WHERE status = 'pending' 
                    ORDER BY requested_at ASC
                    LIMIT 5
                """)
                
                triggers = cursor.fetchall()
                for trigger_id, user_id, days_back in triggers:
                    logger.info(f"Processing manual fetch trigger {trigger_id} for user {user_id} (days_back: {days_back})")
                    
                    # Mark as processing
                    cursor.execute("""
                        UPDATE fetch_triggers 
                        SET status = 'processing' 
                        WHERE id = %s
                    """, (trigger_id,))
                    self.timescale_conn.commit()
                    
                    # Perform the fetch
                    try:
                        stored_count = self.fetch_and_store_data(days_back=days_back)
                        
                        # Mark as completed
                        cursor.execute("""
                            UPDATE fetch_triggers 
                            SET status = 'completed' 
                            WHERE id = %s
                        """, (trigger_id,))
                        self.timescale_conn.commit()
                        
                        logger.info(f"Manual fetch trigger {trigger_id} completed successfully. Stored {stored_count} data points.")
                        
                    except Exception as e:
                        # Mark as failed
                        cursor.execute("""
                            UPDATE fetch_triggers 
                            SET status = 'failed' 
                            WHERE id = %s
                        """, (trigger_id,))
                        self.timescale_conn.commit()
                        
                        logger.error(f"Manual fetch trigger {trigger_id} failed: {e}")
                        
        except Exception as e:
            logger.error(f"Error checking fetch triggers: {e}")

    def run_scheduler(self):
        """Run the scheduler loop"""
        logger.info("Starting scheduler")
        while True:
            # Check for manual triggers more frequently
            self.check_fetch_triggers()
            
            # Run scheduled jobs
            schedule.run_pending()
            
            # Sleep for 5 minutes between checks (instead of 1 hour)
            time.sleep(300)

# Run the service if executed directly
if __name__ == "__main__":
    service = BiometricDataService()
    service.schedule_data_fetch()
    service.run_scheduler()
