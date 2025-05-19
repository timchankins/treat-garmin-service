# Example SQL queries for timescale analytics (Updated with proper JSON key casing)

-- Get average heart rate by hour for a specific day
SELECT 
    time_bucket('1 hour', timestamp) AS hour,
    AVG((value->>'heartRate')::numeric) AS avg_heart_rate
FROM biometric_data
WHERE 
    user_id = 1 
    AND data_type = 'heart_rate' 
    AND metric_name = 'heart_rate.heartRate'
    AND timestamp >= '2025-05-18'::date
    AND timestamp < '2025-05-19'::date
GROUP BY hour
ORDER BY hour;

-- Get step count for each day in the last week
SELECT 
    timestamp::date AS day,
    (value->>'steps')::integer AS steps
FROM biometric_data
WHERE 
    user_id = 1 
    AND data_type = 'steps' 
    AND metric_name = 'steps.count'
    AND timestamp >= NOW() - INTERVAL '7 days'
    AND timestamp < NOW()
ORDER BY day;

-- Find maximum stress level by day
SELECT 
    timestamp::date AS day,
    MAX((value->>'stressLevel')::numeric) AS max_stress
FROM biometric_data
WHERE 
    user_id = 1 
    AND data_type = 'stress' 
    AND metric_name = 'stress.stress'
    AND timestamp >= NOW() - INTERVAL '30 days'
GROUP BY day
ORDER BY day;

-- Calculate average resting heart rate over time
SELECT 
    time_bucket('1 day', timestamp) AS day,
    AVG((value->>'restingHeartRate')::numeric) AS avg_rhr
FROM biometric_data
WHERE 
    user_id = 1 
    AND data_type = 'heart_rate' 
    AND metric_name = 'heart_rate.restingHeartRate'
    AND timestamp >= NOW() - INTERVAL '90 days'
GROUP BY day
ORDER BY day;

-- Create a continuous aggregate view for heart rate data
CREATE MATERIALIZED VIEW heart_rate_hourly
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', timestamp) AS bucket,
    user_id,
    AVG((value->>'heartRate')::numeric) AS avg_heart_rate,
    MIN((value->>'heartRate')::numeric) AS min_heart_rate,
    MAX((value->>'heartRate')::numeric) AS max_heart_rate,
    COUNT(*) AS reading_count
FROM biometric_data
WHERE 
    data_type = 'heart_rate' 
    AND metric_name = 'heart_rate.heartRate'
GROUP BY bucket, user_id;

-- Add a refresh policy to update the continuous aggregate
SELECT add_continuous_aggregate_policy('heart_rate_hourly',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

-- Find correlation between sleep duration and resting heart rate
WITH sleep_data AS (
    SELECT 
        timestamp::date AS day,
        (value->>'sleepTimeSeconds')::numeric / 3600 AS sleep_hours
    FROM biometric_data
    WHERE 
        user_id = 1 
        AND data_type = 'sleep' 
        AND metric_name = 'sleep.sleepTimeSeconds'
        AND timestamp >= NOW() - INTERVAL '30 days'
),
heart_data AS (
    SELECT 
        timestamp::date AS day,
        (value->>'restingHeartRate')::numeric AS resting_hr
    FROM biometric_data
    WHERE 
        user_id = 1 
        AND data_type = 'heart_rate' 
        AND metric_name = 'heart_rate.restingHeartRate'
        AND timestamp >= NOW() - INTERVAL '30 days'
)
SELECT 
    corr(sleep_hours, resting_hr) AS correlation
FROM 
    sleep_data
JOIN 
    heart_data USING (day);
