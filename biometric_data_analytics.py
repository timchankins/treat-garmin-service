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
                if not user_data or not start_date or not end_date:
                    continue
                
                # Calculate general metrics
                daily_metrics = self._calculate_daily_metrics(user_data)
                
                # Calculate averages for the period
                avg_metrics = self._calculate_average_metrics(daily_metrics)
                
                # Calculate trend metrics
                trend_metrics = self._calculate_trend_metrics(daily_metrics)
                
                # Calculate correlation metrics
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
    
    def _calculate_daily_metrics(self, user_data):
        """Calculate daily metrics from user data"""
        try:
            daily_metrics = {}
            
            # Process steps data
            if 'steps' in user_data:
                for date, metrics in user_data['steps'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    if 'steps' in metrics:
                        daily_metrics[date]['steps'] = int(metrics['steps']) if metrics['steps'] else 0
            
            # Process heart rate data
            if 'heart_rate' in user_data:
                for date, metrics in user_data['heart_rate'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    if 'restingHeartRate' in metrics:
                        value = metrics['restingHeartRate']
                        daily_metrics[date]['resting_hr'] = float(value) if value else None
                    
                    # Calculate average heart rate if available
                    avg_hr = None
                    hr_values = []
                    for key, value in metrics.items():
                        if key.startswith('heartRateValues') and value is not None:
                            try:
                                hr_values.append(float(value))
                            except (ValueError, TypeError):
                                pass
                    
                    if hr_values:
                        avg_hr = sum(hr_values) / len(hr_values)
                        daily_metrics[date]['avg_hr'] = avg_hr
            
            # Process sleep data
            if 'sleep' in user_data:
                for date, metrics in user_data['sleep'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    sleep_duration = None
                    deep_sleep = None
                    
                    if 'sleepTimeSeconds' in metrics:
                        value = metrics['sleepTimeSeconds']
                        if value:
                            sleep_duration = float(value) / 3600  # Convert to hours
                            daily_metrics[date]['sleep_duration'] = sleep_duration
                    
                    if 'deepSleepSeconds' in metrics:
                        value = metrics['deepSleepSeconds']
                        if value:
                            deep_sleep = float(value) / 3600  # Convert to hours
                            daily_metrics[date]['deep_sleep'] = deep_sleep
            
            # Process stress data
            if 'stress' in user_data:
                for date, metrics in user_data['stress'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    if 'avgStressLevel' in metrics:
                        value = metrics['avgStressLevel']
                        daily_metrics[date]['avg_stress'] = float(value) if value else None
            
            # Process HRV data
            if 'hrv' in user_data:
                for date, metrics in user_data['hrv'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    if 'avgHRV' in metrics:
                        value = metrics['avgHRV']
                        daily_metrics[date]['avg_hrv'] = float(value) if value else None
            
            # Process body battery data
            if 'body_battery' in user_data:
                for date, metrics in user_data['body_battery'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    battery_values = []
                    for key, value in metrics.items():
                        if key.startswith('bodyBatteryValue') and value is not None:
                            try:
                                battery_values.append(float(value))
                            except (ValueError, TypeError):
                                pass
                    
                    if battery_values:
                        avg_battery = sum(battery_values) / len(battery_values)
                        daily_metrics[date]['avg_body_battery'] = avg_battery
            
            # Process SPO2 data
            if 'spo2' in user_data:
                for date, metrics in user_data['spo2'].items():
                    if date not in daily_metrics:
                        daily_metrics[date] = {}
                    
                    spo2_values = []
                    for key, value in metrics.items():
                        if key.startswith('avgSpo2') and value is not None:
                            try:
                                spo2_values.append(float(value))
                            except (ValueError, TypeError):
                                pass
                    
                    if spo2_values:
                        avg_spo2 = sum(spo2_values) / len(spo2_values)
                        daily_metrics[date]['avg_spo2'] = avg_spo2
            
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
                            'slope': slope,
                            'r_squared': r_value**2,
                            'p_value': p_value,
                            'significant': p_value < 0.05
                        }

                        # Calculate percentage change
                        if len(y) > 1 and y[0] != 0:
                            pct_change = (y[-1] - y[0]) / y[0] * 100
                            trend_metrics[f'{column}_pct_change'] = pct_change
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
            
            # Convert to dictionary format
            correlation_metrics['correlations'] = corr_matrix.to_dict()
            
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
                            'correlation': corr_value,
                            'strength': 'strong' if abs(corr_value) > 0.7 else 'moderate'
                        })
            
            correlation_metrics['important_correlations'] = important_correlations
            
            return correlation_metrics
        except Exception as e:
            logger.error(f"Failed to calculate correlation metrics: {e}")
            return {}
    
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
