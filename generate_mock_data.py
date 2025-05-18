#!/usr/bin/env python3
# generate_mock_data.py
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

# User ID to use for mock data
USER_ID = 1  # This should match the user ID in your database

# Date range for generating data
DAYS_BACK = 30
START_DATE = datetime.date.today() - datetime.timedelta(days=DAYS_BACK)
END_DATE = datetime.date.today()

# Mock data generators
def generate_steps_data(date):
    """Generate mock steps data for a given date"""
    base_steps = 8000
    # Generate more realistic step counts with weekly patterns
    if date.weekday() >= 5:  # Weekend
        base_steps = 6000  # Less steps on weekends
    
    # Add some randomness
    steps = int(base_steps + random.randint(-2000, 3000))
    
    return {
        "steps": steps,
        "activeTimeSeconds": random.randint(int(steps/20), int(steps/15)),
        "activeTimeMins": random.randint(int(steps/1200), int(steps/900)),
        "distanceMeters": steps * random.uniform(0.7, 0.8),
        "activeCalories": int(steps * random.uniform(0.04, 0.06)),
        "totalCalories": int(steps * random.uniform(0.06, 0.08))
    }

def generate_heart_rate_data(date):
    """Generate mock heart rate data for a given date"""
    # Base resting heart rate
    resting_hr = random.randint(55, 65)
    
    # Generate random heart rate zones
    return {
        "restingHeartRate": resting_hr,
        "maxHeartRate": random.randint(140, 180),
        "averageHeartRate": random.randint(resting_hr + 10, resting_hr + 30),
        "heartRateZones": {
            "zone1": random.randint(400, 800),
            "zone2": random.randint(300, 600),
            "zone3": random.randint(200, 400),
            "zone4": random.randint(100, 300),
            "zone5": random.randint(0, 100)
        }
    }

def generate_sleep_data(date):
    """Generate mock sleep data for a given date"""
    # Base sleep in seconds (7-8 hours)
    sleep_seconds = random.randint(25200, 28800)  
    
    return {
        "sleepTimeSeconds": sleep_seconds,
        "deepSleepSeconds": random.randint(int(sleep_seconds * 0.1), int(sleep_seconds * 0.25)),
        "lightSleepSeconds": random.randint(int(sleep_seconds * 0.4), int(sleep_seconds * 0.6)),
        "remSleepSeconds": random.randint(int(sleep_seconds * 0.15), int(sleep_seconds * 0.25)),
        "awakeSleepSeconds": random.randint(int(sleep_seconds * 0.05), int(sleep_seconds * 0.1)),
        "sleepScoreQualifier": random.choice(["EXCELLENT", "GOOD", "FAIR", "POOR"]),
        "sleepScore": random.randint(60, 95)
    }

def generate_stress_data(date):
    """Generate mock stress data for a given date"""
    avg_stress = random.randint(25, 45)
    
    return {
        "avgStress": avg_stress,
        "maxStress": random.randint(avg_stress + 20, 99),
        "stressDuration": random.randint(6 * 3600, 16 * 3600),  # 6-16 hours in seconds
        "restStressDuration": random.randint(4 * 3600, 8 * 3600),  # 4-8 hours in seconds
        "activityStressDuration": random.randint(2 * 3600, 6 * 3600),  # 2-6 hours in seconds
        "lowStressDuration": random.randint(3600, 4 * 3600),  # 1-4 hours in seconds
        "mediumStressDuration": random.randint(1800, 3 * 3600),  # 30min-3 hours in seconds
        "highStressDuration": random.randint(0, 3600)  # 0-1 hour in seconds
    }

def generate_hrv_data(date):
    """Generate mock HRV data for a given date"""
    avg_hrv = random.randint(35, 65)
    
    return {
        "avgHRV": avg_hrv,
        "minHRV": random.randint(avg_hrv - 20, avg_hrv - 5),
        "maxHRV": random.randint(avg_hrv + 5, avg_hrv + 30),
        "hrvStatus": random.choice(["OPTIMAL", "BALANCED", "LOW", "POOR"]),
        "feedbackPhrase": random.choice([
            "Your body appears ready for challenges today.",
            "Your HRV shows good recovery.",
            "Signs of fatigue detected. Take it easy today.",
            "Your body may need additional rest."
        ])
    }

def generate_body_battery_data(date):
    """Generate mock Body Battery data for a given date"""
    charged = random.randint(60, 100)
    drained = random.randint(30, 70)
    
    return {
        "bodyBatteryCharged": charged,
        "bodyBatteryDrained": drained,
        "bodyBatteryMax": random.randint(charged, 100),
        "bodyBatteryMin": random.randint(10, 40),
        "bodyBatteryEnd": random.randint(20, 60)
    }

def generate_spo2_data(date):
    """Generate mock SpO2 data for a given date"""
    return {
        "avgSpo2": random.randint(94, 99),
        "minSpo2": random.randint(90, 94),
        "maxSpo2": random.randint(97, 100),
        "onDemandReadingCount": random.randint(0, 5),
        "avgSleepSpo2": random.randint(94, 99)
    }

def generate_respiration_data(date):
    """Generate mock respiration data for a given date"""
    avg_resp = random.randint(14, 18)
    
    return {
        "avgWakingRespirationValue": avg_resp,
        "minWakingRespirationValue": random.randint(avg_resp - 4, avg_resp - 1),
        "maxWakingRespirationValue": random.randint(avg_resp + 1, avg_resp + 6),
        "avgSleepRespirationValue": random.randint(12, 16),
        "minSleepRespirationValue": random.randint(8, 11),
        "maxSleepRespirationValue": random.randint(16, 20)
    }

# Map of data types to generator functions
DATA_GENERATORS = {
    "steps": generate_steps_data,
    "heart_rate": generate_heart_rate_data,
    "sleep": generate_sleep_data,
    "stress": generate_stress_data,
    "hrv": generate_hrv_data,
    "body_battery": generate_body_battery_data,
    "spo2": generate_spo2_data,
    "respiration": generate_respiration_data
}

def save_to_timescale(user_id, date, data_type, data):
    """Save mock data to TimescaleDB"""
    connection = None
    try:
        # Connect to TimescaleDB
        connection = psycopg2.connect(**timescale_conn_params)
        cursor = connection.cursor()
        
        timestamp = datetime.datetime.combine(date, datetime.time())
        
        rows = []
        # Handle dictionary data
        if isinstance(data, dict):
            # Flatten data for storage
            for metric_name, value in data.items():
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
        
        if rows:
            logger.info(f"Inserting {len(rows)} rows for {data_type} data on {date}")
            # Insert data into biometric_data table
            psycopg2.extras.execute_values(
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
            
            connection.commit()
            logger.info(f"Successfully saved {len(rows)} rows for {data_type} on {date}")
            return True
        else:
            logger.warning(f"No rows to insert for {data_type}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to save {data_type} data: {e}")
        if connection:
            connection.rollback()
        return False
    finally:
        if connection:
            connection.close()

def trigger_analytics(user_id):
    """Trigger analytics calculation"""
    connection = None
    try:
        # Connect to PostgreSQL analytics database
        postgres_conn_params = {
            "dbname": os.getenv("POSTGRES_DB_NAME", "analytics_data"),
            "user": os.getenv("POSTGRES_DB_USER", "postgres"),
            "password": os.getenv("POSTGRES_DB_PASSWORD", "postgres"),
            "host": os.getenv("POSTGRES_DB_HOST", "localhost"),
            "port": os.getenv("POSTGRES_DB_PORT", "5432")
        }
        
        connection = psycopg2.connect(**postgres_conn_params)
        cursor = connection.cursor()
        
        # Insert a job into the analytics queue
        cursor.execute("""
            INSERT INTO analytics_jobs (user_id, status)
            VALUES (%s, 'pending')
        """, (user_id,))
        
        connection.commit()
        logger.info(f"Triggered analytics calculation for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to trigger analytics: {e}")
        if connection:
            connection.rollback()
        return False
    finally:
        if connection:
            connection.close()

def generate_mock_data():
    """Generate and save mock data for all supported types"""
    current_date = START_DATE
    data_count = 0
    
    while current_date <= END_DATE:
        logger.info(f"Generating mock data for {current_date}")
        
        for data_type, generator in DATA_GENERATORS.items():
            # Generate mock data
            data = generator(current_date)
            # Save to database
            if save_to_timescale(USER_ID, current_date, data_type, data):
                data_count += 1
        
        current_date += datetime.timedelta(days=1)
    
    logger.info(f"Generated and saved {data_count} mock data points")
    
    # Trigger analytics calculation
    trigger_analytics(USER_ID)
    
    return data_count

if __name__ == "__main__":
    total_data_points = generate_mock_data()
    print(f"Successfully generated {total_data_points} mock data points.")
    print("Mock data generation complete!")