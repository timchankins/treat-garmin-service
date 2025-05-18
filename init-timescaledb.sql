-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create biometric_data table
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
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Create TimescaleDB hypertable
SELECT create_hypertable('biometric_data', 'timestamp', if_not_exists => TRUE);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_biometric_user_type_time 
ON biometric_data (user_id, data_type, timestamp DESC);
