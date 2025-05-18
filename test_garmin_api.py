#!/usr/bin/env python
# test_garmin_api.py - Simple script to test Garmin API functionality
import os
import datetime
from dotenv import load_dotenv
from garminconnect import Garmin
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('GarminTest')

# Load credentials
load_dotenv()
email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")

if not email or not password:
    raise ValueError("Missing GARMIN_EMAIL or GARMIN_PASSWORD in .env")

# Valid and safe methods to fetch daily metrics
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

def safe_call(client, method_name, date):
    """Safely call a method on the Garmin client"""
    if hasattr(client, method_name):
        method = getattr(client, method_name)
        try:
            result = method(date)
            if result:
                logger.info(f"Method {method_name} for {date} returned data of type: {type(result)}")
                if isinstance(result, dict):
                    logger.info(f"Dict keys: {list(result.keys())}")
                elif isinstance(result, list):
                    logger.info(f"List length: {len(result)}")
                return True, method_name, "Success"
            else:
                logger.warning(f"Method {method_name} for {date} returned no data (None or empty)")
                return False, method_name, "No data returned"
        except Exception as e:
            logger.error(f"Error calling {method_name}: {e}")
            return False, method_name, f"Error: {e}"
    else:
        logger.warning(f"Method {method_name} not found in Garmin client")
        return False, method_name, "Method not found"

def main():
    """Main test function"""
    try:
        # Create and login to Garmin Connect
        logger.info(f"Attempting to login with email: {email}")
        client = Garmin(email, password)
        client.login()
        logger.info("✅ Logged in to Garmin Connect successfully")
        
        # Test API calls for today and yesterday
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        
        dates_to_test = [today, yesterday]
        
        # Track results
        success_count = 0
        total_tests = 0
        
        # Test each method with each date
        for date in dates_to_test:
            logger.info(f"Testing API calls for date: {date.isoformat()}")
            
            for method_name in AVAILABLE_METHODS:
                total_tests += 1
                success, name, message = safe_call(client, method_name, date)
                if success:
                    success_count += 1
                    logger.info(f"✅ {name}: {message}")
                else:
                    logger.warning(f"❌ {name}: {message}")
        
        # Report results
        logger.info(f"Test complete: {success_count}/{total_tests} methods returned data")
        if success_count == 0:
            logger.error("No methods returned data! Check Garmin account and internet connection.")
        elif success_count < total_tests // 2:
            logger.warning("Less than half of the methods returned data. This may indicate issues with the Garmin API or account.")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")

if __name__ == "__main__":
    main()