# biometric_data_analytics.py
import os
import time
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor
from dotenv import load_dotenv
import json
from scipy import stats
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('BiometricDataAnalytics')

class BiometricDataAnalytics:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
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
        
        # Set up analytics tables
        self._setup_postgres_db()
        
        # Processing interval in seconds
        self.processing_interval = int(os.getenv("ANALYTICS_PROCESSING_INTERVAL", "300"))
    
    def _setup_postgres_db(self):
        """Connect to PostgreSQL and set up necessary tables"""
        try:
            # Connect to PostgreSQL
            conn = psycopg2.connect(**self.postgres_conn_params)
            
            # Create tables if they don't exist
            with conn.cursor() as cursor:
                # Analytics jobs queue
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS analytics_jobs (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # User analytics table
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
                
                # Analytics metrics metadata
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
                
                # Insert some initial metadata if table is empty
                cursor.execute("SELECT COUNT(*) FROM analytics_metrics_metadata")
                if cursor.fetchone()[0] == 0:
                    execute_values(
                        cursor,
                        """
                        INSERT INTO analytics_metrics_metadata 
                        (metric_name, display_name, description, unit, data_type, visualization_type)
                        VALUES %s
                        """,
                        [
                            ('avg_steps', 'Average Steps', 'Average daily steps', 'steps', 'integer', 'line'),
                            ('avg_heart_rate', 'Average Heart Rate', 'Average daily heart rate', 'bpm', 'float', 'line'),
                            ('avg_stress', 'Average Stress Level', 'Average daily stress level', 'score', 'float', 'line'),
                            ('avg_hrv', 'Average Heart Rate Variability', 'Average daily HRV', 'ms', 'float', 'line'),
                            ('avg_rhr', 'Average Resting Heart Rate', 'Average resting heart rate', 'bpm', 'float', 'line'),
                            ('avg_sleep_duration', 'Average Sleep Duration', 'Average sleep duration', 'hours', 'float', 'bar'),
                            ('avg_body_battery', 'Average Body Battery', 'Average body battery level', 'score', 'float', 'line'),
                            ('avg_spo2', 'Average Blood Oxygen', 'Average blood oxygen level', '%', 'float', 'line'),
                            ('total_active_time', 'Total Active Time', 'Total active time', 'minutes', 'integer', 'bar'),
                            ('recovery_score', 'Recovery Score', 'Calculated recovery score', 'score', 'float', 'gauge'),
                            ('training_load', 'Training Load', 'Calculated training load', 'score', 'float', 'line'),
                            ('fitness_trend', 'Fitness Trend', 'Fitness level trend', 'score', 'float', 'line'),
                        ]
                    )
                
                conn.commit()
                
            logger.info("PostgreSQL setup complete")
        except Exception as e:
            logger.error(f"Failed to setup PostgreSQL: {e}")
            if 'conn' in locals() and conn:
                conn.close()
            raise
    
    def _get_pending_jobs(self):
        """Get pending analytics jobs"""
        try:
            conn = psycopg2.connect(**self.postgres_conn_params)
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM analytics_jobs 
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                """)
                jobs = cursor.fetchall()
            conn.close()
            return jobs
        except Exception as e:
            logger.error(f"Failed to get pending jobs: {e}")
            return []
    
    def _update_job_status(self, job_id, status):
        """Update job status"""
        try:
            conn = psycopg2.connect(**self.postgres_conn_params)
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE analytics_jobs
                    SET status = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (status, job_id))
                conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to update job status: {e}")
    
    def _get_user_data(self, user_id, days_back=30):
        """Get user biometric data from TimescaleDB"""
        try:
            conn = psycopg2.connect(**self.timescale_conn_params)
            data = {}
            
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT timestamp::date as date, data_type, metric_name, value
                    FROM biometric_data
                    WHERE user_id = %s
                      AND timestamp >= %s
                      AND timestamp <= %s
                    ORDER BY timestamp DESC
                """, (user_id, start_date, end_date))
                
                rows = cursor.fetchall()
                logger.info(f"Retrieved {len(rows)} raw data rows for user {user_id} ({start_date} to {end_date})")
                
                # Organize data by type and date
                for row in rows:
                    date_str = row['date'].isoformat()
                    data_type = row['data_type']
                    metric_name = row['metric_name']
                    value = row['value']
                    
                    if data_type not in data:
                        data[data_type] = {}
                    
                    if date_str not in data[data_type]:
                        data[data_type][date_str] = {}
                    
                    data[data_type][date_str][metric_name] = value
            
            conn.close()
            return data, start_date.date(), end_date.date()
        except Exception as e:
            logger.error(f"Failed to get user data: {e}")
            return {}, None, None
     
    def _calculate_daily_metrics(self, user_data):
        """Calculate daily metrics from user data"""
        try:
            daily_metrics = {}
            
            # Process steps data
            if 'steps' in user_data:
                for date, metrics in user_data['steps'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    # Handle both direct steps and step intervals
                    total_steps = 0
                    step_count = 0
                    
                    for metric_name, value in metrics.items():
                        try:
                            # Parse JSON value if it's a string
                            if isinstance(value, str):
                                value_data = json.loads(value)
                            elif isinstance(value, dict):
                                value_data = value
                            else:
                                continue
                            
                            # Handle steps.count format
                            if metric_name == 'steps.count' and 'count' in value_data:
                                step_count = max(step_count, int(value_data['count']) if value_data['count'] else 0)
                            
                            # Handle steps.item_X format (interval data)
                            elif metric_name.startswith('steps.item_') and 'steps' in value_data:
                                total_steps += int(value_data['steps']) if value_data['steps'] else 0
                            
                            # Handle direct steps field (legacy format)
                            elif metric_name == 'steps' and isinstance(value_data, (int, float)):
                                step_count = max(step_count, int(value_data))
                                
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
                    
                    # Use the higher value between count and aggregated intervals
                    daily_metrics[date]['steps'] = max(step_count, total_steps)
            
            # Process heart rate data
            if 'heart_rate' in user_data:
                for date, metrics in user_data['heart_rate'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    hr_values = []
                    
                    for metric_name, value in metrics.items():
                        try:
                            # Parse JSON value if it's a string
                            if isinstance(value, str):
                                value_data = json.loads(value)
                            elif isinstance(value, dict):
                                value_data = value
                            else:
                                continue
                            
                            # Handle various heart rate fields
                            if 'restingHeartRate' in value_data and value_data['restingHeartRate']:
                                daily_metrics[date]['resting_hr'] = float(value_data['restingHeartRate'])
                            elif 'value' in value_data and value_data['value'] and metric_name.startswith('heart_rate'):
                                hr_values.append(float(value_data['value']))
                            elif 'avgHeartRate' in value_data and value_data['avgHeartRate']:
                                hr_values.append(float(value_data['avgHeartRate']))
                            elif 'heartRateValues' in value_data and value_data['heartRateValues']:
                                if isinstance(value_data['heartRateValues'], list):
                                    hr_values.extend([float(x) for x in value_data['heartRateValues'] if x])
                                else:
                                    hr_values.append(float(value_data['heartRateValues']))
                                    
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
                    
                    # Calculate average heart rate
                    if hr_values:
                        daily_metrics[date]['avg_hr'] = sum(hr_values) / len(hr_values)
            
            # Process resting heart rate data separately
            if 'resting_hr' in user_data:
                for date, metrics in user_data['resting_hr'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    for metric_name, value in metrics.items():
                        try:
                            # Parse JSON value if it's a string
                            if isinstance(value, str):
                                value_data = json.loads(value)
                            elif isinstance(value, dict):
                                value_data = value
                            else:
                                continue
                            
                            # Look for resting heart rate values
                            if 'value' in value_data and value_data['value']:
                                daily_metrics[date]['resting_hr'] = float(value_data['value'])
                            elif 'restingHeartRate' in value_data and value_data['restingHeartRate']:
                                daily_metrics[date]['resting_hr'] = float(value_data['restingHeartRate'])
                                
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
            
            # Process sleep data
            if 'sleep' in user_data:
                for date, metrics in user_data['sleep'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    for metric_name, value in metrics.items():
                        try:
                            # Parse JSON value if it's a string
                            if isinstance(value, str):
                                value_data = json.loads(value)
                            elif isinstance(value, dict):
                                value_data = value
                            else:
                                continue
                            
                            # Handle various sleep fields
                            if 'sleepTimeSeconds' in value_data and value_data['sleepTimeSeconds']:
                                daily_metrics[date]['sleep_duration'] = float(value_data['sleepTimeSeconds']) / 3600
                            elif 'totalSleepTimeSeconds' in value_data and value_data['totalSleepTimeSeconds']:
                                daily_metrics[date]['sleep_duration'] = float(value_data['totalSleepTimeSeconds']) / 3600
                            elif 'deepSleepSeconds' in value_data and value_data['deepSleepSeconds']:
                                daily_metrics[date]['deep_sleep'] = float(value_data['deepSleepSeconds']) / 3600
                                
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
            
            # Process stress data
            if 'stress' in user_data:
                for date, metrics in user_data['stress'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    stress_values = []
                    
                    for metric_name, value in metrics.items():
                        try:
                            # Parse JSON value if it's a string
                            if isinstance(value, str):
                                value_data = json.loads(value)
                            elif isinstance(value, dict):
                                value_data = value
                            else:
                                continue
                            
                            # Handle various stress fields
                            if 'avgStressLevel' in value_data and value_data['avgStressLevel']:
                                stress_values.append(float(value_data['avgStressLevel']))
                            elif 'overallStressLevel' in value_data and value_data['overallStressLevel']:
                                stress_values.append(float(value_data['overallStressLevel']))
                            elif 'value' in value_data and value_data['value'] and metric_name.startswith('stress'):
                                stress_values.append(float(value_data['value']))
                                
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
                    
                    if stress_values:
                        daily_metrics[date]['avg_stress'] = sum(stress_values) / len(stress_values)
            
            # Process HRV data
            if 'hrv' in user_data:
                for date, metrics in user_data['hrv'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    # Track separate HRV metrics
                    hrv_weekly_avg = None
                    hrv_last_night_avg = None
                    hrv_5min_high = None
                    hrv_5min_low = None
                    hrv_readings = []
                    legacy_hrv = []
                    
                    for metric_name, value in metrics.items():
                        try:
                            # Parse JSON value if it's a string
                            if isinstance(value, str):
                                value_data = json.loads(value)
                            elif isinstance(value, dict):
                                value_data = value
                            else:
                                continue
                            
                            # Handle specific HRV fields separately
                            if 'weeklyAvg' in value_data and value_data['weeklyAvg']:
                                hrv_weekly_avg = float(value_data['weeklyAvg'])
                            elif 'lastNightAvg' in value_data and value_data['lastNightAvg']:
                                hrv_last_night_avg = float(value_data['lastNightAvg'])
                            elif 'lastNight5MinHigh' in value_data and value_data['lastNight5MinHigh']:
                                hrv_5min_high = float(value_data['lastNight5MinHigh'])
                            elif 'lastNight5MinLow' in value_data and value_data['lastNight5MinLow']:
                                hrv_5min_low = float(value_data['lastNight5MinLow'])
                            elif 'hrvValue' in value_data and value_data['hrvValue']:
                                hrv_readings.append(float(value_data['hrvValue']))
                            elif 'avgHRV' in value_data and value_data['avgHRV']:
                                legacy_hrv.append(float(value_data['avgHRV']))
                            elif 'value' in value_data and value_data['value'] and metric_name.startswith('hrv'):
                                legacy_hrv.append(float(value_data['value']))
                                
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
                    
                    # Store separate HRV metrics
                    if hrv_weekly_avg is not None:
                        daily_metrics[date]['hrv_weekly_avg'] = hrv_weekly_avg
                    if hrv_last_night_avg is not None:
                        daily_metrics[date]['hrv_last_night_avg'] = hrv_last_night_avg
                    if hrv_5min_high is not None:
                        daily_metrics[date]['hrv_5min_high'] = hrv_5min_high
                    if hrv_5min_low is not None:
                        daily_metrics[date]['hrv_5min_low'] = hrv_5min_low
                    if hrv_readings:
                        daily_metrics[date]['hrv_readings_avg'] = sum(hrv_readings) / len(hrv_readings)
                    
                    # Primary HRV metric: prioritize lastNightAvg, then fall back to other metrics
                    primary_hrv = None
                    if hrv_last_night_avg is not None:
                        primary_hrv = hrv_last_night_avg
                    elif hrv_weekly_avg is not None:
                        primary_hrv = hrv_weekly_avg
                    elif hrv_readings:
                        primary_hrv = sum(hrv_readings) / len(hrv_readings)
                    elif legacy_hrv:
                        primary_hrv = sum(legacy_hrv) / len(legacy_hrv)
                    
                    if primary_hrv is not None:
                        daily_metrics[date]['avg_hrv'] = primary_hrv
            
            # Process body battery data
            if 'body_battery' in user_data:
                for date, metrics in user_data['body_battery'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    battery_values = []
                    
                    for metric_name, value in metrics.items():
                        try:
                            # Parse JSON value if it's a string
                            if isinstance(value, str):
                                value_data = json.loads(value)
                            elif isinstance(value, dict):
                                value_data = value
                            else:
                                continue
                            
                            # Handle various body battery fields
                            if 'bodyBatteryValue' in value_data and value_data['bodyBatteryValue']:
                                battery_values.append(float(value_data['bodyBatteryValue']))
                            elif 'value' in value_data and value_data['value'] and metric_name.startswith('body_battery'):
                                battery_values.append(float(value_data['value']))
                                
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
                    
                    if battery_values:
                        daily_metrics[date]['avg_body_battery'] = sum(battery_values) / len(battery_values)
            
            # Process SPO2 data
            if 'spo2' in user_data:
                for date, metrics in user_data['spo2'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    spo2_values = []
                    
                    for metric_name, value in metrics.items():
                        try:
                            # Parse JSON value if it's a string
                            if isinstance(value, str):
                                value_data = json.loads(value)
                            elif isinstance(value, dict):
                                value_data = value
                            else:
                                continue
                            
                            # Handle various SPO2 fields
                            if 'avgSpo2' in value_data and value_data['avgSpo2']:
                                spo2_values.append(float(value_data['avgSpo2']))
                            elif 'value' in value_data and value_data['value'] and metric_name.startswith('spo2'):
                                spo2_values.append(float(value_data['value']))
                                
                        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                            continue
                    
                    if spo2_values:
                        daily_metrics[date]['avg_spo2'] = sum(spo2_values) / len(spo2_values)
            
            logger.info(f"Calculated daily metrics for {len(daily_metrics)} dates")
            
            return daily_metrics
        except Exception as e:
            logger.error(f"Failed to calculate daily metrics: {e}")
            return {}
    
    def _calculate_average_metrics(self, daily_metrics):
        """Calculate average metrics across days"""
        try:
            avg_metrics = {}
            
            # Metrics to calculate averages for
            metrics_to_avg = [
                'steps', 'resting_hr', 'avg_hr', 'sleep_duration', 
                'deep_sleep', 'avg_stress', 'avg_hrv', 'avg_body_battery', 'avg_spo2'
            ]
            
            # Calculate averages
            for metric in metrics_to_avg:
                values = []
                for date, metrics in daily_metrics.items():
                    if metric in metrics and metrics[metric] is not None:
                        values.append(metrics[metric])
                
                if values:
                    avg_metrics[f'avg_{metric}'] = sum(values) / len(values)
                    avg_metrics[f'min_{metric}'] = min(values)
                    avg_metrics[f'max_{metric}'] = max(values)
            
            # Calculate additional derived metrics
            if 'avg_sleep_duration' in avg_metrics and 'avg_deep_sleep' in avg_metrics:
                if avg_metrics['avg_sleep_duration'] > 0:
                    avg_metrics['deep_sleep_ratio'] = avg_metrics['avg_deep_sleep'] / avg_metrics['avg_sleep_duration']
            
            return avg_metrics
        except Exception as e:
            logger.error(f"Failed to calculate average metrics: {e}")
            return {}
    
    def _calculate_trend_metrics(self, daily_metrics):
        """Calculate trend metrics from daily data"""
        try:
            trend_metrics = {}

            # Convert to pandas DataFrame for easier analysis
            df = pd.DataFrame.from_dict(daily_metrics, orient='index')
            if df.empty:
                return {}

            # Sort by date
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            # Calculate trends for different metrics
            for column in df.columns:
                if df[column].notna().sum() >= 3:  # Need at least 3 points for trend
                    try:
                        # Simple linear regression for trend
                        x = np.arange(len(df[column].dropna()))
                        y = df[column].dropna().values
                        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

                        # Store trend information
                        trend_metrics[f'{column}_trend'] = {
                            'slope': float(slope),
                            'r_squared': float(r_value**2),
                            'p_value': float(p_value),
                            'significant': bool(p_value < 0.05)
                        }

                        # Calculate percentage change
                        if len(y) > 1 and y[0] != 0:
                            pct_change = (y[-1] - y[0]) / y[0] * 100
                            trend_metrics[f'{column}_pct_change'] = float(pct_change)
                    except:
                        # Skip metrics that can't be analyzed
                        pass

            return trend_metrics
        except Exception as e:
            logger.error(f"Failed to calculate trend metrics: {e}")
            return {}
    
    def _calculate_correlation_metrics(self, daily_metrics):
        """Calculate correlation between different metrics"""
        try:
            correlation_metrics = {}
            
            # Convert to pandas DataFrame for correlation analysis
            df = pd.DataFrame.from_dict(daily_metrics, orient='index')
            if df.empty or df.shape[1] < 2:  # Need at least 2 metrics
                return {}
            
            # Calculate correlation matrix
            corr_matrix = df.corr(method='pearson', min_periods=3)
            
            # Convert to dictionary format with proper JSON serialization
            correlations_dict = {}
            for col1 in corr_matrix.columns:
                correlations_dict[col1] = {}
                for col2 in corr_matrix.columns:
                    val = corr_matrix.loc[col1, col2]
                    correlations_dict[col1][col2] = float(val) if not np.isnan(val) else None
            
            correlation_metrics['correlations'] = correlations_dict
            
            # Extract important correlations
            important_correlations = []
            for i in range(len(corr_matrix.columns)):
                for j in range(i+1, len(corr_matrix.columns)):
                    col1 = corr_matrix.columns[i]
                    col2 = corr_matrix.columns[j]
                    corr_value = corr_matrix.iloc[i, j]
                    
                    if not np.isnan(corr_value) and abs(corr_value) > 0.5:
                        important_correlations.append({
                            'metric1': col1,
                            'metric2': col2,
                            'correlation': float(corr_value),
                            'strength': 'strong' if abs(corr_value) > 0.7 else 'moderate'
                        })
            
            correlation_metrics['important_correlations'] = important_correlations
            
            return correlation_metrics
        except Exception as e:
            logger.error(f"Failed to calculate correlation metrics: {e}")
            return {}
    
    def _store_detailed_metrics(self, user_id, daily_metrics, start_date, end_date):
        """Store detailed metrics in a structured format for efficient querying"""
        try:
            conn = psycopg2.connect(**self.postgres_conn_params)
            with conn.cursor() as cursor:
                # First, ensure we have the detailed_metrics table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS detailed_metrics (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        date DATE NOT NULL,
                        metric_name VARCHAR(100) NOT NULL,
                        metric_value FLOAT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (user_id, date, metric_name)
                    )
                """)

                # Create index for faster queries
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_detailed_metrics_user_date
                    ON detailed_metrics (user_id, date)
                """)

                # Insert the detailed metrics
                rows = []
                for date_str, metrics in daily_metrics.items():
                    date_obj = datetime.fromisoformat(date_str).date()
                    for metric_name, value in metrics.items():
                        if value is not None:
                            rows.append((
                                user_id,
                                date_obj,
                                metric_name,
                                float(value)
                            ))

                # Use batch insert for efficiency
                if rows:
                    execute_values(
                        cursor,
                        """
                        INSERT INTO detailed_metrics (user_id, date, metric_name, metric_value)
                        VALUES %s
                        ON CONFLICT (user_id, date, metric_name)
                        DO UPDATE SET
                            metric_value = EXCLUDED.metric_value,
                            created_at = CURRENT_TIMESTAMP
                        """,
                        rows,
                        page_size=100
                    )

                    conn.commit()
                    logger.info(f"Stored {len(rows)} detailed metrics for user {user_id}")
                    return True

            conn.close()
            return False
        except Exception as e:
            logger.error(f"Failed to store detailed metrics: {e}")
            if 'conn' in locals() and conn:
                conn.rollback()
            return False

    def _calculate_analytics(self, user_id):
        """Calculate analytics for user"""
        try:
            # Get user data for different time ranges
            analytics_results = []

            # Define time ranges to analyze
            time_ranges = {
                'week': 7,
                'month': 30,
                'quarter': 90
            }

            for range_name, days_back in time_ranges.items():
                user_data, start_date, end_date = self._get_user_data(user_id, days_back)
                logger.info(f"Retrieved data for {range_name}: {len(user_data)} data types, date range: {start_date} to {end_date}")
                if not user_data or not start_date or not end_date:
                    logger.warning(f"No data found for {range_name} range")
                    continue

                # Calculate general metrics
                daily_metrics = self._calculate_daily_metrics(user_data)
                logger.info(f"Calculated daily metrics for {range_name}: {len(daily_metrics)} days")

                # NEW: Store detailed metrics in structured format
                self._store_detailed_metrics(user_id, daily_metrics, start_date, end_date)

                # Continue with existing analytics calculations
                avg_metrics = self._calculate_average_metrics(daily_metrics)
                trend_metrics = self._calculate_trend_metrics(daily_metrics)
                correlation_metrics = self._calculate_correlation_metrics(daily_metrics)

                # Combine all metrics
                all_metrics = {
                    **avg_metrics,
                    **trend_metrics,
                    **correlation_metrics
                }

                # Add to results
                analytics_results.append({
                    'user_id': user_id,
                    'analytics_type': 'biometric',
                    'time_range': range_name,
                    'start_date': start_date,
                    'end_date': end_date,
                    'metrics': all_metrics
                })

            return analytics_results
        except Exception as e:
            logger.error(f"Failed to calculate analytics: {e}")
            return []

    def _save_analytics_results(self, results):
        """Save analytics results to PostgreSQL"""
        try:
            if not results:
                return False
            
            conn = psycopg2.connect(**self.postgres_conn_params)
            with conn.cursor() as cursor:
                for result in results:
                    cursor.execute("""
                        INSERT INTO user_analytics 
                        (user_id, analytics_type, time_range, start_date, end_date, metrics)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, analytics_type, time_range, start_date, end_date) 
                        DO UPDATE SET metrics = EXCLUDED.metrics, created_at = CURRENT_TIMESTAMP
                    """, (
                        result['user_id'],
                        result['analytics_type'],
                        result['time_range'],
                        result['start_date'],
                        result['end_date'],
                        json.dumps(result['metrics'])
                    ))
                
                conn.commit()
            
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to save analytics results: {e}")
            return False
    
    def _process_job(self, job):
        """Process an analytics job"""
        try:
            job_id = job['id']
            user_id = job['user_id']
            
            logger.info(f"Processing analytics job {job_id} for user {user_id}")
            
            # Update job status to processing
            self._update_job_status(job_id, 'processing')
            
            # Calculate analytics
            results = self._calculate_analytics(user_id)
            
            # Save results
            if self._save_analytics_results(results):
                self._update_job_status(job_id, 'completed')
                logger.info(f"Job {job_id} completed successfully")
            else:
                self._update_job_status(job_id, 'failed')
                logger.error(f"Failed to save results for job {job_id}")
        
        except Exception as e:
            logger.error(f"Error processing job {job['id']}: {e}")
            self._update_job_status(job['id'], 'failed')
    
    def run_processor(self):
        """Run the analytics processor loop"""
        logger.info("Starting analytics processor")
        retry_count = 0
        max_retries = 5
        
        while True:
            try:
                # Process pending jobs
                jobs = self._get_pending_jobs()
                for job in jobs:
                    self._process_job(job)
                
                # Reset retry counter on success
                retry_count = 0
                
                # Sleep for the configured interval
                time.sleep(self.processing_interval)
            except Exception as e:
                retry_count += 1
                wait_time = min(60, 2 ** retry_count + random.uniform(0, 1))  # Exponential backoff
                logger.error(f"Error in analytics processor: {e}, retrying in {wait_time:.1f} seconds (attempt {retry_count}/{max_retries})")
                
                if retry_count > max_retries:
                    logger.critical("Exceeded maximum retry attempts, exiting")
                    break
                    
                time.sleep(wait_time)

# Run the service if executed directly
if __name__ == "__main__":
    analytics_service = BiometricDataAnalytics()
    analytics_service.run_processor()
