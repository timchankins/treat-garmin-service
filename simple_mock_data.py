#!/usr/bin/env python3
# simple_mock_data.py - A simplified mock data generator
import os
import json
import random
import datetime
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MockDataGenerator')

# Load environment variables
load_dotenv()

# Database connection parameters
timescale_conn_params = {
    "dbname": os.getenv("TIMESCALE_DB_NAME", "biometric_data"),
    "user": os.getenv("TIMESCALE_DB_USER", "postgres"),
    "password": os.getenv("TIMESCALE_DB_PASSWORD", "postgres"),
    "host": os.getenv("TIMESCALE_DB_HOST", "localhost"),
    "port": os.getenv("TIMESCALE_DB_PORT", "5432")
}

postgres_conn_params = {
    "dbname": os.getenv("POSTGRES_DB_NAME", "analytics_data"),
    "user": os.getenv("POSTGRES_DB_USER", "postgres"),
    "password": os.getenv("POSTGRES_DB_PASSWORD", "postgres"),
    "host": os.getenv("POSTGRES_DB_HOST", "localhost"),
    "port": os.getenv("POSTGRES_DB_PORT", "5432")
}

# Date range for mock data
START_DATE = datetime.date.today() - datetime.timedelta(days=7)

def setup_databases():
    """Ensure databases are properly set up"""
    # Set up TimescaleDB
    conn = None
    try:
        conn = psycopg2.connect(**timescale_conn_params)
        with conn.cursor() as cursor:
            # Create users table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create biometric_data table if not exists
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
            
            # Try to convert to hypertable if not already
            try:
                cursor.execute("""
                    SELECT create_hypertable('biometric_data', 'timestamp', if_not_exists => TRUE)
                """)
            except Exception as e:
                logger.warning(f"Could not create hypertable: {e}")
            
            # Create index if not exists
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_biometric_user_type_time 
                ON biometric_data (user_id, data_type, timestamp DESC)
            """)
            
            # Insert test user
            cursor.execute("""
                INSERT INTO users (email) 
                VALUES ('test@example.com') 
                ON CONFLICT (email) DO NOTHING
                RETURNING id
            """)
            
            result = cursor.fetchone()
            if result:
                user_id = result[0]
            else:
                cursor.execute("SELECT id FROM users WHERE email = 'test@example.com'")
                user_id = cursor.fetchone()[0]
            
            conn.commit()
            logger.info(f"TimescaleDB setup complete, user_id: {user_id}")
            return user_id
    except Exception as e:
        logger.error(f"Failed to setup TimescaleDB: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def setup_analytics_db():
    """Set up the PostgreSQL analytics database"""
    conn = None
    try:
        conn = psycopg2.connect(**postgres_conn_params)
        with conn.cursor() as cursor:
            # Create analytics jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analytics_jobs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create user analytics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_analytics (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    analytics_type VARCHAR(50) NOT NULL,
                    time_range VARCHAR(20) NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    metrics JSONB NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, analytics_type, time_range, start_date, end_date)
                )
            """)
            
            # Create analytics metrics metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analytics_metrics_metadata (
                    id SERIAL PRIMARY KEY,
                    metric_name VARCHAR(100) NOT NULL,
                    display_name VARCHAR(100) NOT NULL,
                    description TEXT,
                    unit VARCHAR(20),
                    data_type VARCHAR(20) NOT NULL,
                    visualization_type VARCHAR(20) DEFAULT 'line',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (metric_name)
                )
            """)
            
            conn.commit()
            logger.info("PostgreSQL analytics database setup complete")
            return True
    except Exception as e:
        logger.error(f"Failed to setup PostgreSQL analytics database: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def insert_mock_biometric_data(user_id):
    """Insert mock biometric data for testing"""
    conn = None
    try:
        conn = psycopg2.connect(**timescale_conn_params)
        with conn.cursor() as cursor:
            # Generate 7 days of data
            current_date = START_DATE
            end_date = datetime.date.today()
            row_count = 0
            
            while current_date <= end_date:
                # Generate steps data
                steps = random.randint(6000, 12000)
                cursor.execute("""
                    INSERT INTO biometric_data (user_id, timestamp, data_type, metric_name, value, raw_data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, timestamp, data_type, metric_name) DO UPDATE
                    SET value = EXCLUDED.value, raw_data = EXCLUDED.raw_data
                """, (
                    user_id,
                    current_date,
                    'steps',
                    'steps',
                    json.dumps(steps),
                    json.dumps({'steps': steps, 'activeTimeSeconds': steps * 0.5})
                ))
                row_count += 1
                
                # Generate heart rate data
                resting_hr = random.randint(55, 70)
                cursor.execute("""
                    INSERT INTO biometric_data (user_id, timestamp, data_type, metric_name, value, raw_data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, timestamp, data_type, metric_name) DO UPDATE
                    SET value = EXCLUDED.value, raw_data = EXCLUDED.raw_data
                """, (
                    user_id,
                    current_date,
                    'heart_rate',
                    'restingHeartRate',
                    json.dumps(resting_hr),
                    json.dumps({'restingHeartRate': resting_hr, 'maxHeartRate': resting_hr + 80})
                ))
                row_count += 1
                
                # Generate sleep data
                sleep_hours = random.uniform(6.0, 8.5)
                sleep_seconds = int(sleep_hours * 3600)
                cursor.execute("""
                    INSERT INTO biometric_data (user_id, timestamp, data_type, metric_name, value, raw_data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, timestamp, data_type, metric_name) DO UPDATE
                    SET value = EXCLUDED.value, raw_data = EXCLUDED.raw_data
                """, (
                    user_id,
                    current_date,
                    'sleep',
                    'sleepTimeSeconds',
                    json.dumps(sleep_seconds),
                    json.dumps({'sleepTimeSeconds': sleep_seconds, 'deepSleepSeconds': int(sleep_seconds * 0.2)})
                ))
                row_count += 1
                
                # Generate stress data
                stress = random.randint(25, 50)
                cursor.execute("""
                    INSERT INTO biometric_data (user_id, timestamp, data_type, metric_name, value, raw_data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, timestamp, data_type, metric_name) DO UPDATE
                    SET value = EXCLUDED.value, raw_data = EXCLUDED.raw_data
                """, (
                    user_id,
                    current_date,
                    'stress',
                    'avgStress',
                    json.dumps(stress),
                    json.dumps({'avgStress': stress, 'maxStress': stress + 30})
                ))
                row_count += 1
                
                # Move to next day
                current_date += datetime.timedelta(days=1)
            
            conn.commit()
            logger.info(f"Inserted {row_count} rows of mock biometric data")
            return row_count
    except Exception as e:
        logger.error(f"Failed to insert mock biometric data: {e}")
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()

def insert_mock_analytics(user_id):
    """Insert mock analytics data for testing"""
    conn = None
    try:
        conn = psycopg2.connect(**postgres_conn_params)
        with conn.cursor() as cursor:
            # Mock metrics
            metrics = {
                'avg_steps': 8765,
                'avg_resting_hr': 64.3,
                'avg_sleep_duration': 7.2,
                'avg_avg_stress': 35.7,
                'total_active_time': 423,
                'recovery_score': 82,
                'correlations': {
                    'steps': {
                        'steps': 1.0,
                        'restingHeartRate': -0.3,
                        'sleep': 0.6,
                        'stress': -0.5
                    },
                    'restingHeartRate': {
                        'steps': -0.3,
                        'restingHeartRate': 1.0,
                        'sleep': -0.4,
                        'stress': 0.7
                    }
                }
            }
            
            # Insert mock analytics
            for time_range in ['week', 'month', 'quarter']:
                cursor.execute("""
                    INSERT INTO user_analytics 
                    (user_id, analytics_type, time_range, start_date, end_date, metrics)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, analytics_type, time_range, start_date, end_date) DO UPDATE
                    SET metrics = EXCLUDED.metrics
                """, (
                    user_id,
                    'biometric',
                    time_range,
                    START_DATE,
                    datetime.date.today(),
                    json.dumps(metrics)
                ))
            
            # Create pending analytics job
            cursor.execute("""
                INSERT INTO analytics_jobs (user_id, status)
                VALUES (%s, 'pending')
            """, (user_id,))
            
            conn.commit()
            logger.info("Inserted mock analytics data")
            return True
    except Exception as e:
        logger.error(f"Failed to insert mock analytics data: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def main():
    """Main function to run the mock data generator"""
    logger.info("Setting up databases...")
    setup_analytics_db()
    user_id = setup_databases()
    
    if user_id:
        logger.info(f"Inserting mock data for user ID: {user_id}")
        rows = insert_mock_biometric_data(user_id)
        if rows > 0:
            logger.info(f"Successfully inserted {rows} rows of mock biometric data")
            if insert_mock_analytics(user_id):
                logger.info("Successfully inserted mock analytics data")
            else:
                logger.error("Failed to insert mock analytics data")
        else:
            logger.error("Failed to insert mock biometric data")
    else:
        logger.error("Failed to set up databases or get user ID")

if __name__ == "__main__":
    main()