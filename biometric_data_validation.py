#!/usr/bin/env python3
# biometric_data_validation.py - A script to validate biometric data in TimescaleDB
import os
import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional, Set, Union
from dataclasses import dataclass
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('BiometricDataValidator')

@dataclass
class ValidationRule:
    """Defines a validation rule for a specific metric"""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    expected_types: Optional[List[type]] = None
    required: bool = False
    jsonb_path: Optional[str] = None  # Path to extract value from JSONB
    custom_validation: Optional[callable] = None
    
@dataclass
class ValidationResult:
    """Stores the result of a validation check"""
    metric_name: str
    data_type: str
    timestamp: datetime
    is_valid: bool
    error_message: Optional[str] = None
    value: Any = None
    
class BiometricDataValidator:
    def __init__(self):
        """Initialize the validator with configuration and database connection"""
        # Load environment variables
        load_dotenv()
        
        # Database connection parameters from environment variables
        self.db_params = {
            "dbname": os.getenv("TIMESCALE_DB_NAME", "biometric_data"),
            "user": os.getenv("TIMESCALE_DB_USER", "postgres"),
            "password": os.getenv("TIMESCALE_DB_PASSWORD", "postgres"),
            "host": os.getenv("TIMESCALE_DB_HOST", "localhost"),
            "port": os.getenv("TIMESCALE_DB_PORT", "5432")
        }
        
        # Connection object will be initialized when needed
        self.conn = None
        
        # Define validation rules for different data types
        self.validation_rules = {
            "body_battery": {
                "value": ValidationRule(min_value=0, max_value=100, required=True)
            },
            "heart_rate": {
                "restingHeartRate": ValidationRule(min_value=30, max_value=120, required=True)
            },
            "stress": {
                "avgStress": ValidationRule(min_value=0, max_value=100, required=True)
            },
            "sleep": {
                "sleepTimeSeconds": ValidationRule(min_value=0, max_value=43200, required=True)  # Max 12 hours
            },
            "steps": {
                "steps": ValidationRule(min_value=0, max_value=100000, required=True)  # Max 100k steps
            },
            "fitness_age": {
                "fitnessAge": ValidationRule(min_value=10, max_value=100, required=False)
            }
        }
        
    def connect_to_db(self) -> None:
        """Establish connection to the database"""
        try:
            if self.conn is None or self.conn.closed:
                logger.info(f"Connecting to database {self.db_params['dbname']} on {self.db_params['host']}")
                self.conn = psycopg2.connect(**self.db_params)
                logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
            
    def close_connection(self) -> None:
        """Close the database connection if it's open"""
        if self.conn and not self.conn.closed:
            self.conn.close()
            logger.info("Database connection closed")
            
    def fetch_data_for_validation(self, start_date: str, end_date: str, user_id: Optional[int] = None) -> Dict[str, List[Dict]]:
        """
        Fetch biometric data for the specified date range and user
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            user_id: Optional user ID (if None, will fetch data for all users)
            
        Returns:
            Dictionary mapping data_type to list of data records
        """
        self.connect_to_db()
        
        data_by_type = {}
        
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Build the query based on parameters
                query = """
                    SELECT 
                        id, user_id, timestamp, data_type, metric_name, 
                        value, raw_data
                    FROM 
                        biometric_data
                    WHERE 
                        timestamp::date BETWEEN %s AND %s
                """
                params = [start_date, end_date]
                
                if user_id is not None:
                    query += " AND user_id = %s"
                    params.append(user_id)
                
                # Add ordering
                query += " ORDER BY data_type, timestamp"
                
                # Execute the query
                cursor.execute(query, params)
                results = cursor.fetchall()
                
                # Group data by data_type
                for row in results:
                    data_type = row['data_type']
                    if data_type not in data_by_type:
                        data_by_type[data_type] = []
                    data_by_type[data_type].append(dict(row))
                
                logger.info(f"Fetched {len(results)} records across {len(data_by_type)} data types")
                
        except Exception as e:
            logger.error(f"Error fetching data for validation: {e}")
            raise
            
        return data_by_type
    
    def extract_value_from_jsonb(self, jsonb_data: Dict, key: str) -> Any:
        """
        Extract a value from JSONB data, handling nested paths
        
        Args:
            jsonb_data: The JSONB data as a Python dictionary
            key: The key to extract, can be a simple key or a dot-notation path
            
        Returns:
            The extracted value or None if not found
        """
        if not jsonb_data:
            return None
            
        # Handle simple keys
        if '.' not in key:
            return jsonb_data.get(key)
            
        # Handle nested paths using dot notation
        parts = key.split('.')
        current = jsonb_data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current
    
    def validate_record(self, record: Dict) -> ValidationResult:
        """
        Validate a single biometric data record against defined rules
        
        Args:
            record: A dictionary containing a biometric data record
            
        Returns:
            ValidationResult object with validation details
        """
        data_type = record['data_type']
        metric_name = record['metric_name']
        timestamp = record['timestamp']
        
        # Skip validation if we don't have rules for this data type
        if data_type not in self.validation_rules:
            return ValidationResult(
                metric_name=metric_name,
                data_type=data_type,
                timestamp=timestamp,
                is_valid=True,
                value=None
            )
            
        # Parse the JSONB value
        try:
            value_json = record['value']
            if isinstance(value_json, str):
                value_data = json.loads(value_json)
            else:
                value_data = value_json
        except (json.JSONDecodeError, TypeError):
            return ValidationResult(
                metric_name=metric_name,
                data_type=data_type,
                timestamp=timestamp,
                is_valid=False,
                error_message=f"Invalid JSON format in value field",
                value=record['value']
            )
            
        # Determine which specific rule to apply based on metric_name
        rule_key = metric_name.split('.')[-1] if '.' in metric_name else metric_name
        
        # If we don't have a specific rule for this metric, use the default rule for the data type
        if rule_key not in self.validation_rules[data_type]:
            # Try with a more generic approach
            for potential_key in self.validation_rules[data_type]:
                if potential_key in metric_name:
                    rule_key = potential_key
                    break
            else:
                # No matching rule found
                return ValidationResult(
                    metric_name=metric_name,
                    data_type=data_type,
                    timestamp=timestamp,
                    is_valid=True,  # Assume valid if no rule
                    value=value_data
                )
        
        # Get the validation rule
        rule = self.validation_rules[data_type][rule_key]
        
        # Extract the value to validate
        if rule.jsonb_path:
            value_to_validate = self.extract_value_from_jsonb(value_data, rule.jsonb_path)
        else:
            # Try some common patterns to extract the value
            if isinstance(value_data, dict):
                if rule_key in value_data:
                    value_to_validate = value_data[rule_key]
                elif 'value' in value_data:
                    value_to_validate = value_data['value']
                elif len(value_data) == 1:
                    # If there's only one key, use its value
                    value_to_validate = next(iter(value_data.values()))
                else:
                    value_to_validate = value_data
            else:
                value_to_validate = value_data
        
        # Validate the value
        if value_to_validate is None and rule.required:
            return ValidationResult(
                metric_name=metric_name,
                data_type=data_type,
                timestamp=timestamp,
                is_valid=False,
                error_message=f"Required value is missing",
                value=value_data
            )
        
        if value_to_validate is not None:
            # Type validation
            if rule.expected_types and not any(isinstance(value_to_validate, t) for t in rule.expected_types):
                return ValidationResult(
                    metric_name=metric_name,
                    data_type=data_type,
                    timestamp=timestamp,
                    is_valid=False,
                    error_message=f"Value has incorrect type: {type(value_to_validate).__name__}",
                    value=value_to_validate
                )
            
            # Range validation for numeric values
            if isinstance(value_to_validate, (int, float)):
                if rule.min_value is not None and value_to_validate < rule.min_value:
                    return ValidationResult(
                        metric_name=metric_name,
                        data_type=data_type,
                        timestamp=timestamp,
                        is_valid=False,
                        error_message=f"Value {value_to_validate} is below minimum {rule.min_value}",
                        value=value_to_validate
                    )
                
                if rule.max_value is not None and value_to_validate > rule.max_value:
                    return ValidationResult(
                        metric_name=metric_name,
                        data_type=data_type,
                        timestamp=timestamp,
                        is_valid=False,
                        error_message=f"Value {value_to_validate} exceeds maximum {rule.max_value}",
                        value=value_to_validate
                    )
            
            # Custom validation
            if rule.custom_validation:
                try:
                    is_valid, error_msg = rule.custom_validation(value_to_validate)
                    if not is_valid:
                        return ValidationResult(
                            metric_name=metric_name,
                            data_type=data_type,
                            timestamp=timestamp,
                            is_valid=False,
                            error_message=error_msg,
                            value=value_to_validate
                        )
                except Exception as e:
                    return ValidationResult(
                        metric_name=metric_name,
                        data_type=data_type,
                        timestamp=timestamp,
                        is_valid=False,
                        error_message=f"Custom validation error: {str(e)}",
                        value=value_to_validate
                    )
        
        # If we got here, the validation passed
        return ValidationResult(
            metric_name=metric_name,
            data_type=data_type,
            timestamp=timestamp,
            is_valid=True,
            value=value_to_validate
        )
    
    def validate_data(self, start_date: str, end_date: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Validate all biometric data for the specified date range and user
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            user_id: Optional user ID (if None, will validate data for all users)
            
        Returns:
            Validation report with statistics and errors
        """
        # Fetch data for validation
        data_by_type = self.fetch_data_for_validation(start_date, end_date, user_id)
        
        # Initialize validation report
        validation_report = {
            "summary": {
                "start_date": start_date,
                "end_date": end_date,
                "user_id": user_id,
                "data_types_found": list(data_by_type.keys()),
                "total_records": sum(len(records) for records in data_by_type.values()),
                "valid_records": 0,
                "invalid_records": 0,
                "validation_time": datetime.now().isoformat()
            },
            "data_type_stats": {},
            "errors": []
        }
        
        # Validate each data type
        for data_type, records in data_by_type.items():
            data_type_stats = {
                "total_records": len(records),
                "valid_records": 0,
                "invalid_records": 0,
                "metrics_found": set()
            }
            
            for record in records:
                validation_result = self.validate_record(record)
                
                # Update metric names found
                data_type_stats["metrics_found"].add(validation_result.metric_name)
                
                # Track validation results
                if validation_result.is_valid:
                    data_type_stats["valid_records"] += 1
                    validation_report["summary"]["valid_records"] += 1
                else:
                    data_type_stats["invalid_records"] += 1
                    validation_report["summary"]["invalid_records"] += 1
                    
                    # Add to errors list
                    validation_report["errors"].append({
                        "data_type": data_type,
                        "metric_name": validation_result.metric_name,
                        "timestamp": validation_result.timestamp.isoformat(),
                        "error_message": validation_result.error_message,
                        "value": validation_result.value
                    })
            
            # Convert set to list for JSON serialization
            data_type_stats["metrics_found"] = list(data_type_stats["metrics_found"])
            
            # Add data type stats to report
            validation_report["data_type_stats"][data_type] = data_type_stats
        
        return validation_report
    
    def get_data_quality_metrics(self, validation_report: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate data quality metrics from a validation report
        
        Args:
            validation_report: The validation report from validate_data()
            
        Returns:
            Dictionary of data quality metrics
        """
        summary = validation_report["summary"]
        total_records = summary["total_records"]
        
        if total_records == 0:
            return {
                "validity_rate": 0,
                "data_completeness": 0,
                "error_distribution": {}
            }
        
        # Calculate validity rate
        validity_rate = (summary["valid_records"] / total_records) * 100
        
        # Calculate data completeness (check if we have all expected data types)
        expected_data_types = set(self.validation_rules.keys())
        found_data_types = set(summary["data_types_found"])
        data_completeness = (len(found_data_types.intersection(expected_data_types)) / 
                            len(expected_data_types)) * 100
        
        # Calculate error distribution by data type
        error_distribution = {}
        for data_type, stats in validation_report["data_type_stats"].items():
            if stats["total_records"] > 0:
                error_rate = (stats["invalid_records"] / stats["total_records"]) * 100
                error_distribution[data_type] = {
                    "error_rate": error_rate,
                    "invalid_records": stats["invalid_records"],
                    "total_records": stats["total_records"]
                }
        
        return {
            "validity_rate": validity_rate,
            "data_completeness": data_completeness,
            "error_distribution": error_distribution
        }
    
    def generate_detailed_report(self, validation_report: Dict[str, Any], quality_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a detailed report combining validation results and quality metrics
        
        Args:
            validation_report: The validation report from validate_data()
            quality_metrics: The quality metrics from get_data_quality_metrics()
            
        Returns:
            Dictionary with detailed report information
        """
        return {
            "validation_summary": validation_report["summary"],
            "quality_metrics": quality_metrics,
            "data_type_stats": validation_report["data_type_stats"],
            "errors": validation_report["errors"],
            "recommendations": self._generate_recommendations(validation_report, quality_metrics)
        }
    
    def _generate_recommendations(self, validation_report: Dict[str, Any], quality_metrics: Dict[str, Any]) -> List[str]:
        """
        Generate recommendations based on validation results
        
        Args:
            validation_report: The validation report
            quality_metrics: The quality metrics
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        # Check overall validity rate
        if quality_metrics["validity_rate"] < 95:
            recommendations.append(
                f"Overall data validity rate is {quality_metrics['validity_rate']:.1f}%, which is below the recommended 95%. "
                f"Review error patterns to identify systematic issues."
            )
        
        # Check data completeness
        if quality_metrics["data_completeness"] < 100:
            missing_data_types = set(self.validation_rules.keys()) - set(validation_report["summary"]["data_types_found"])
            recommendations.append(
                f"Data completeness is {quality_metrics['data_completeness']:.1f}%. Missing data types: {', '.join(missing_data_types)}"
            )
        
        # Check for specific data types with high error rates
        for data_type, stats in quality_metrics["error_distribution"].items():
            if stats["error_rate"] > 10:
                recommendations.append(
                    f"{data_type} has an error rate of {stats['error_rate']:.1f}%, which is above the threshold of 10%. "
                    f"({stats['invalid_records']} out of {stats['total_records']} records are invalid)"
                )
        
        # Check for days with missing data
        start_date = datetime.strptime(validation_report["summary"]["start_date"], "%Y-%m-%d")
        end_date = datetime.strptime(validation_report["summary"]["end_date"], "%Y-%m-%d")
        date_range = (end_date - start_date).days + 1
        
        for data_type, stats in validation_report["data_type_stats"].items():
            if data_type in self.validation_rules and stats["total_records"] < date_range:
                recommendations.append(
                    f"{data_type} has fewer records ({stats['total_records']}) than expected for the date range ({date_range} days). "
                    f"Some days may be missing data."
                )
        
        # If no recommendations, add a positive note
        if not recommendations:
            recommendations.append(
                "Data quality looks good! No significant issues were detected in the validation process."
            )
        
        return recommendations

def main():
    """Main function to run the validation script"""
    parser = argparse.ArgumentParser(description='Validate biometric data in TimescaleDB')
    parser.add_argument('--start-date', type=str, default='2025-05-30',
                        help='Start date for validation (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default='2025-06-04',
                        help='End date for validation (YYYY-MM-DD)')
    parser.add_argument('--user-id', type=int, help='User ID to validate (optional)')
    parser.add_argument('--output', type=str, help='Output file for validation report (optional)')
    
    args = parser.parse_args()
    
    validator = BiometricDataValidator()
    
    try:
        logger.info(f"Starting validation for date range {args.start_date} to {args.end_date}")
        
        # Run validation
        validation_report = validator.validate_data(args.start_date, args.end_date, args.user_id)
        
        # Calculate quality metrics
        quality_metrics = validator.get_data_quality_metrics(validation_report)
        
        # Generate detailed report
        detailed_report = validator.generate_detailed_report(validation_report, quality_metrics)
        
        # Output report
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(detailed_report, f, indent=2, default=str)
            logger.info(f"Detailed validation report saved to {args.output}")
        else:
            # Print summary to console
            print("\n=== BIOMETRIC DATA VALIDATION SUMMARY ===")
            print(f"Date Range: {args.start_date} to {args.end_date}")
            print(f"Total Records: {validation_report['summary']['total_records']}")
            print(f"Valid Records: {validation_report['summary']['valid_records']} ({quality_metrics['validity_rate']:.1f}%)")
            print(f"Invalid Records: {validation_report['summary']['invalid_records']}")
            print(f"Data Completeness: {quality_metrics['data_completeness']:.1f}%")
            print("\nData Types Found:")
            for data_type in validation_report['summary']['data_types_found']:
                stats = validation_report['data_type_stats'][data_type]
                print(f"  - {data_type}: {stats['valid_records']}/{stats['total_records']} valid records")
            
            print("\nRecommendations:")
            for i, rec in enumerate(detailed_report['recommendations'], 1):
                print(f"  {i}. {rec}")
            
            if validation_report['errors']:
                print(f"\nFound {len(validation_report['errors'])} validation errors. First 5 errors:")
                for i, error in enumerate(validation_report['errors'][:5], 1):
                    print(f"  {i}. {error['data_type']} - {error['metric_name']} - {error['error_message']}")
            
            print("\nFor complete details, run with --output option to save to a file")
        
        return 0
    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        return 1
    finally:
        validator.close_connection()

if __name__ == "__main__":
    exit(main())

