# Troubleshooting Guide

This document provides detailed troubleshooting steps for common issues with the Garmin Biometric Service.

## Dealing with Empty Garmin API Data

If the Garmin Connect API returns empty data despite successful authentication, there are several possible causes and solutions:

### Diagnosing the Issue

1. **Check the logs for API responses**:
   ```bash
   docker-compose logs -f biometric_data_service | grep "returned no data"
   ```
   
   If you see logs like:
   ```
   BiometricDataService - WARNING - Method get_steps_data for 2025-05-18 returned no data (None or empty)
   ```
   This confirms the API is successfully authenticating but returning empty data.

2. **Verify the Garmin account**:
   - Ensure your Garmin Connect account has data for the requested timeframe
   - Check if you can view the data on the Garmin Connect website/app
   - Verify your device is syncing properly with Garmin Connect

3. **Check for API limitations**:
   - Garmin may have rate limits or restrictions on API access
   - Your account privacy settings might restrict data access

### Solutions

#### 1. Update Garmin API Library

The Garmin API connectivity often improves with newer versions of the `garminconnect` library:

```bash
# Check compatibility with the test script
python test_garmin_api.py

# If it shows successful API calls, rebuild the service
docker-compose build biometric_data_service
docker-compose restart biometric_data_service

# Check logs to confirm it's working
docker-compose logs -f biometric_data_service
```

#### 2. Using Mock Data for Testing

We've added a mock data generator to help test the complete pipeline:

```bash
# Run the mock data service directly
docker-compose up -d mockdata

# Or run it locally
python generate_mock_data.py
```

This will populate your database with realistic mock data to test the dashboard and analytics components.

#### 2. Check Garmin Connect Privacy Settings

1. Log in to your Garmin Connect account at [connect.garmin.com](https://connect.garmin.com)
2. Navigate to Account Settings > Privacy Settings
3. Ensure that data access is not restricted
4. Save changes and try again

#### 3. Sync Your Garmin Device

1. Open the Garmin Connect app on your phone
2. Manually sync your device
3. Verify data appears in the Garmin Connect app
4. Try fetching data again

#### 4. Verify Data Timeframe

The service fetches data for the past `DAYS_TO_FETCH` days (default: 7). Ensure:

1. Your device has collected data during this timeframe
2. Modify the `.env` file to change the timeframe if needed:
   ```
   DAYS_TO_FETCH=14
   ```

#### 5. Try Different API Methods

Some Garmin Connect accounts might have certain data types but not others:

1. Check `biometric_data_service.py` for the `AVAILABLE_METHODS` dictionary
2. Temporarily modify this to only use methods that are likely to return data for your account

## Database Schema Issues

If the TimescaleDB schema verification is failing:

1. **Check the database schema**:
   ```bash
   docker exec -it garmin-biometric-service-timescaledb-1 psql -U postgres -d biometric_data -c "\d+ biometric_data"
   ```

2. **Fix hypertable issues**:
   ```bash
   docker exec -it garmin-biometric-service-timescaledb-1 psql -U postgres -d biometric_data -c "SELECT create_hypertable('biometric_data', 'timestamp', if_not_exists => TRUE);"
   ```

## Analytics Service Issues

If analytics aren't being calculated properly:

1. **Check the analytics_jobs table**:
   ```bash
   docker exec -it garmin-biometric-service-postgres-1 psql -U postgres -d analytics_data -c "SELECT * FROM analytics_jobs ORDER BY created_at DESC LIMIT 10;"
   ```

2. **Check for analytics service errors**:
   ```bash
   docker-compose logs -f analytics_service | grep ERROR
   ```

3. **Manually trigger analytics calculation**:
   ```bash
   docker exec -it garmin-biometric-service-postgres-1 psql -U postgres -d analytics_data -c "INSERT INTO analytics_jobs (user_id, status) VALUES (1, 'pending');"
   ```

## Dashboard Issues

If the dashboard shows tooltips but no data:

1. **Check if data exists in the database**:
   ```bash
   docker exec -it garmin-biometric-service-timescaledb-1 psql -U postgres -d biometric_data -c "SELECT COUNT(*) FROM biometric_data;"
   ```

2. **Use the mock data generator** to populate the database with test data:
   ```bash
   docker-compose up -d mockdata
   ```

3. **Verify analytics results exist**:
   ```bash
   docker exec -it garmin-biometric-service-postgres-1 psql -U postgres -d analytics_data -c "SELECT * FROM user_analytics ORDER BY created_at DESC LIMIT 1;"
   ```