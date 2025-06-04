# db_utils.py
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import pandas as pd
import os
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Centralized database connection and query management"""
    
    def __init__(self):
        self.timescale_conn_params = {
            "dbname": os.getenv("TIMESCALE_DB_NAME", "biometric_data"),
            "user": os.getenv("TIMESCALE_DB_USER", "postgres"),
            "password": os.getenv("TIMESCALE_DB_PASSWORD", "postgres"),
            "host": os.getenv("TIMESCALE_DB_HOST", "localhost"),
            "port": os.getenv("TIMESCALE_DB_PORT", "5432")
        }
        
        self.postgres_conn_params = {
            "dbname": os.getenv("POSTGRES_DB_NAME", "analytics_data"),
            "user": os.getenv("POSTGRES_DB_USER", "postgres"),
            "password": os.getenv("POSTGRES_DB_PASSWORD", "postgres"),
            "host": os.getenv("POSTGRES_DB_HOST", "localhost"),
            "port": os.getenv("POSTGRES_DB_PORT", "5432")
        }
    
    @contextmanager
    def get_connection(self, db_type: str = "timescale"):
        """Get database connection with proper cleanup"""
        conn_params = self.timescale_conn_params if db_type == "timescale" else self.postgres_conn_params
        conn = None
        try:
            conn = psycopg2.connect(**conn_params)
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database connection error ({db_type}): {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def execute_query(self, query: str, params: Optional[Tuple] = None, 
                     db_type: str = "timescale", fetch: bool = False) -> Optional[List[Dict]]:
        """Execute a single query with parameters"""
        try:
            with self.get_connection(db_type) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(query, params or ())
                    
                    if fetch:
                        results = cursor.fetchall()
                        return [dict(row) for row in results]
                    else:
                        conn.commit()
                        return None
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            raise
    
    def execute_batch(self, query: str, params_list: List[Tuple], 
                     db_type: str = "timescale", page_size: int = 500) -> bool:
        """Execute batch operations using execute_values"""
        try:
            with self.get_connection(db_type) as conn:
                with conn.cursor() as cursor:
                    execute_values(cursor, query, params_list, page_size=page_size)
                    conn.commit()
                return True
        except Exception as e:
            logger.error(f"Batch execution error: {e}")
            return False
    
    def query_to_dataframe(self, query: str, params: Optional[Tuple] = None, 
                          db_type: str = "timescale") -> pd.DataFrame:
        """Execute query and return results as pandas DataFrame"""
        try:
            with self.get_connection(db_type) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(query, params or ())
                    results = cursor.fetchall()
                    
                    if results:
                        # Convert to DataFrame
                        df = pd.DataFrame([dict(row) for row in results])
                        return df
                    else:
                        return pd.DataFrame()
        except Exception as e:
            logger.error(f"DataFrame query error: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            return pd.DataFrame()

# Global instance for easy import
db_manager = DatabaseManager()

# Convenience functions for common operations
def get_biometric_data(data_type: Optional[str] = None, days_back: int = 30) -> pd.DataFrame:
    """Fetch biometric data with optional filtering"""
    from datetime import datetime, timedelta
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    query = """
        SELECT
            timestamp::date as date,
            data_type,
            metric_name,
            value
        FROM biometric_data
        WHERE timestamp >= %s
    """
    params = [start_date]
    
    if data_type:
        query += " AND data_type = %s"
        params.append(data_type)
    
    query += " ORDER BY timestamp, data_type, metric_name"
    
    return db_manager.query_to_dataframe(query, tuple(params), "timescale")

def get_analytics_data(time_range: str = 'week') -> pd.DataFrame:
    """Fetch analytics data for given time range"""
    query = """
        SELECT *
        FROM user_analytics
        WHERE time_range = %s
        ORDER BY created_at DESC
        LIMIT 1
    """
    
    return db_manager.query_to_dataframe(query, (time_range,), "postgres")