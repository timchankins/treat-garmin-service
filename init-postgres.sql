-- Analytics jobs queue
CREATE TABLE IF NOT EXISTS analytics_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- User analytics table
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
);

-- Analytics metrics metadata
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
);

-- Insert some initial metadata
INSERT INTO analytics_metrics_metadata 
(metric_name, display_name, description, unit, data_type, visualization_type)
VALUES 
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
('fitness_trend', 'Fitness Trend', 'Fitness level trend', 'score', 'float', 'line')
ON CONFLICT (metric_name) DO NOTHING;
