# dashboard.py
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
from db_utils import db_manager, get_biometric_data, get_analytics_data

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

postgres_conn_params = {
    "dbname": os.getenv("POSTGRES_DB_NAME", "analytics_data"),
    "user": os.getenv("POSTGRES_DB_USER", "postgres"),
    "password": os.getenv("POSTGRES_DB_PASSWORD", "postgres"),
    "host": os.getenv("POSTGRES_DB_HOST", "localhost"),
    "port": os.getenv("POSTGRES_DB_PORT", "5432")
}

# Database connections now handled by db_utils module

# Set up the Streamlit page
st.set_page_config(
    page_title="Biometric Data Dashboard",
    page_icon="❤️",
    layout="wide"
)

st.title("Biometric Data Dashboard")

# Sidebar for controls
st.sidebar.header("Dashboard Controls")
date_range = st.sidebar.selectbox(
    "Select Time Range",
    ["Last 7 Days", "Last 30 Days", "Last 90 Days"]
)

# Map selection to days
days_mapping = {
    "Last 7 Days": 7,
    "Last 30 Days": 30,
    "Last 90 Days": 90
}
days_back = days_mapping[date_range]

# Calculate date range
end_date = datetime.now()
start_date = end_date - timedelta(days=days_back)

# Trigger data fetch
if st.sidebar.button("Fetch Latest Data"):
    st.sidebar.info("Triggering data fetch from Garmin Connect...")
    try:
        # Connect to TimescaleDB to create a trigger for the biometric service
        timescale_conn = psycopg2.connect(**timescale_conn_params)
        with timescale_conn.cursor() as cursor:
            # Create a fetch trigger table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fetch_triggers (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) DEFAULT 'pending',
                    days_back INTEGER DEFAULT 7
                )
            """)
            
            # Get the user ID (assuming the first user)
            cursor.execute("SELECT id FROM users LIMIT 1")
            user_result = cursor.fetchone()
            if user_result:
                user_id = user_result[0]
                
                # Insert a fetch trigger
                cursor.execute("""
                    INSERT INTO fetch_triggers (user_id, days_back)
                    VALUES (%s, %s)
                """, (user_id, 3))  # Fetch last 3 days for immediate update
                timescale_conn.commit()
                
                # Also trigger analytics after the fetch
                postgres_conn = psycopg2.connect(**postgres_conn_params)
                with postgres_conn.cursor() as analytics_cursor:
                    analytics_cursor.execute("""
                        INSERT INTO analytics_jobs (user_id, status)
                        VALUES (%s, 'pending')
                    """, (user_id,))
                    postgres_conn.commit()
                postgres_conn.close()
                
                st.sidebar.success("Data fetch initiated! The biometric service will process this request within a few minutes.")
            else:
                st.sidebar.error("No user found in the system.")
        timescale_conn.close()
    except Exception as e:
        st.sidebar.error(f"Error triggering data fetch: {e}")

def get_detailed_metrics(data_type=None, days_back=30):
    """Fetch and process biometric data for detailed metrics"""
    df = get_biometric_data(data_type, days_back)
    if not df.empty:
        df = process_biometric_data(df, data_type)
    return df

def detect_partial_days(data_type, days_back=30):
    """Detect which days have partial data based on step interval counts"""
    if data_type != 'steps':
        return set()
    
    partial_days = set()
    
    try:
        # Get raw data to count step intervals per day
        raw_df = get_biometric_data(data_type, days_back)
        if raw_df.empty:
            return partial_days
            
        # Count step intervals per day (items that represent 15-minute intervals)
        interval_counts = raw_df[raw_df['metric_name'].str.startswith('steps.item_')].groupby('date').size()
        
        # A full day should have 96 intervals (24 hours * 4 intervals per hour)
        # Consider a day partial if it has significantly fewer intervals
        for date, count in interval_counts.items():
            if count < 80:  # Less than ~83% of expected intervals (allowing some tolerance)
                partial_days.add(date)
                
    except Exception as e:
        st.error(f"Error detecting partial days: {e}")
        
    return partial_days

# Legacy function - now redirects to db_utils
def get_biometric_data_legacy(data_type=None, days_back=30):
    """Legacy function for compatibility - use db_utils.get_biometric_data instead"""
    try:
        df = get_biometric_data(data_type, days_back)
        if not df.empty:
            df = process_biometric_data(df, data_type)
        return df
    except Exception as e:
        st.error(f"Error fetching biometric data: {e}")
        return pd.DataFrame()

def process_biometric_data(df, data_type):
    """Process the raw biometric data to extract meaningful metrics"""
    import json
    
    processed_rows = []
    
    for _, row in df.iterrows():
        try:
            # Parse JSON value if it's a string, otherwise use as-is
            if isinstance(row['value'], str):
                try:
                    value_json = json.loads(row['value'])
                except json.JSONDecodeError:
                    # If it's not valid JSON, treat as string value
                    value_json = {"value": row['value']}
            else:
                value_json = row['value'] if isinstance(row['value'], dict) else {"value": row['value']}
            
            # Process based on data type and extract numeric values
            if data_type == 'steps':
                if row['metric_name'] == 'steps.count' and 'count' in value_json:
                    processed_rows.append({
                        'date': row['date'],
                        'metric_name': 'steps',
                        'value': float(value_json['count'])
                    })
                elif row['metric_name'].startswith('steps.item_') and 'steps' in value_json:
                    processed_rows.append({
                        'date': row['date'],
                        'metric_name': 'step_intervals',
                        'value': float(value_json['steps'])
                    })
            
            elif data_type == 'heart_rate' or data_type == 'resting_hr':
                # Only process the actual resting heart rate, not continuous heart rate data
                if row['metric_name'] == 'heart_rate.restingHeartRate' and 'restingHeartRate' in value_json:
                    processed_rows.append({
                        'date': row['date'],
                        'metric_name': 'restingHeartRate',
                        'value': float(value_json['restingHeartRate'])
                    })
            
            elif data_type == 'sleep':
                # Handle various sleep metrics and extract numeric values
                for key, val in value_json.items():
                    if key in ['sleepTimeSeconds', 'totalSleepTimeSeconds']:
                        processed_rows.append({
                            'date': row['date'],
                            'metric_name': 'sleepTimeSeconds',
                            'value': float(val)
                        })
                    elif key in ['avgOvernightHrv']:
                        processed_rows.append({
                            'date': row['date'],
                            'metric_name': 'avgOvernightHrv',
                            'value': float(val)
                        })
                    elif key in ['bodyBatteryChange']:
                        processed_rows.append({
                            'date': row['date'],
                            'metric_name': 'bodyBatteryChange',
                            'value': float(val)
                        })
                    elif key in ['hrvStatus']:
                        # Convert status to numeric (for aggregation)
                        status_map = {'POOR': 1, 'LOW': 2, 'UNBALANCED': 3, 'BALANCED': 4, 'HIGH': 5}
                        processed_rows.append({
                            'date': row['date'],
                            'metric_name': 'hrvStatus',
                            'value': float(status_map.get(val, 3))  # Default to 3 (UNBALANCED)
                        })
            
            elif data_type == 'stress':
                if 'overallStressLevel' in value_json:
                    processed_rows.append({
                        'date': row['date'],
                        'metric_name': 'stress_level',
                        'value': float(value_json['overallStressLevel'])
                    })
                elif 'avgStressLevel' in value_json:
                    processed_rows.append({
                        'date': row['date'],
                        'metric_name': 'stress_level',
                        'value': float(value_json['avgStressLevel'])
                    })
            
            elif data_type == 'hrv':
                # Handle HRV metrics and extract numeric values
                for key, val in value_json.items():
                    if key in ['weeklyAvg', 'lastNightAvg', 'lastNight5MinHigh', 'lastNight5MinLow']:
                        # Extract HRV summary metrics
                        processed_rows.append({
                            'date': row['date'],
                            'metric_name': key,
                            'value': float(val)
                        })
                    elif key in ['hrvValue']:
                        # Extract individual HRV reading values
                        processed_rows.append({
                            'date': row['date'],
                            'metric_name': 'hrvReading',
                            'value': float(val)
                        })
                    elif key in ['avgHRV', 'avg_hrv']:
                        # Handle legacy avgHRV field
                        processed_rows.append({
                            'date': row['date'],
                            'metric_name': 'avgHRV',
                            'value': float(val)
                        })
            
            else:
                # For other data types, try to extract any numeric values
                for key, val in value_json.items():
                    try:
                        numeric_val = float(val)
                        processed_rows.append({
                            'date': row['date'],
                            'metric_name': f"{row['metric_name']}.{key}",
                            'value': numeric_val
                        })
                    except (ValueError, TypeError):
                        # Skip non-numeric values for aggregation
                        pass
        
        except (KeyError, TypeError, ValueError) as e:
            # If all processing fails, try to extract a simple numeric value
            try:
                simple_value = float(row['value'])
                processed_rows.append({
                    'date': row['date'],
                    'metric_name': row['metric_name'],
                    'value': simple_value
                })
            except (ValueError, TypeError):
                # Skip non-numeric values that can't be processed
                pass
    
    if processed_rows:
        processed_df = pd.DataFrame(processed_rows)
        
        # Aggregate step intervals by day if needed
        if data_type == 'steps' and 'step_intervals' in processed_df['metric_name'].values:
            daily_steps = processed_df[processed_df['metric_name'] == 'step_intervals'].groupby('date')['value'].sum().reset_index()
            daily_steps['metric_name'] = 'steps'
            
            # Combine with step counts
            step_counts = processed_df[processed_df['metric_name'] == 'steps']
            if not step_counts.empty:
                # Use the higher value between count and aggregated intervals
                all_steps = pd.concat([step_counts, daily_steps]).groupby('date')['value'].max().reset_index()
                all_steps['metric_name'] = 'steps'
                
                # Replace step data with processed data
                other_data = processed_df[processed_df['metric_name'] != 'step_intervals']
                other_data = other_data[other_data['metric_name'] != 'steps']
                processed_df = pd.concat([other_data, all_steps], ignore_index=True)
            else:
                processed_df = processed_df[processed_df['metric_name'] != 'step_intervals']
                processed_df.loc[processed_df['metric_name'] == 'step_intervals', 'metric_name'] = 'steps'
        
        return processed_df
    
    return df

# Legacy function - now redirects to db_utils
def get_analytics_data_legacy(time_range='week'):
    """Legacy function for compatibility - use db_utils.get_analytics_data instead"""
    try:
        return get_analytics_data(time_range)
    except Exception as e:
        st.error(f"Error fetching analytics data: {e}")
        return pd.DataFrame()

# Map days_back to time_range
time_range_mapping = {
    7: 'week',
    30: 'month',
    90: 'quarter'
}
time_range = time_range_mapping[days_back]

# Fetch analytics data
analytics_df = get_analytics_data(time_range)

# Main dashboard tabs
tab1, tab2, tab3 = st.tabs(["Overview", "Detailed Metrics", "Analytics Insights"])

with tab1:
    st.header("Biometric Overview")
    
    # Create a summary section
    col1, col2, col3, col4 = st.columns(4)
    
    if not analytics_df.empty and 'metrics' in analytics_df.columns:
        metrics = analytics_df['metrics'].iloc[0]
        
        with col1:
            if 'avg_steps' in metrics:
                st.metric("Average Daily Steps", f"{int(metrics['avg_steps']):,}")
            else:
                st.metric("Average Daily Steps", "No data")
                
        with col2:
            if 'avg_resting_hr' in metrics:
                st.metric("Average Resting HR", f"{metrics['avg_resting_hr']:.1f} bpm")
            else:
                st.metric("Average Resting HR", "No data")
                
        with col3:
            if 'avg_sleep_duration' in metrics:
                st.metric("Average Sleep", f"{metrics['avg_sleep_duration']:.1f} hrs")
            else:
                st.metric("Average Sleep", "No data")
                
        with col4:
            if 'avg_avg_stress' in metrics:
                st.metric("Average Stress Level", f"{metrics['avg_avg_stress']:.1f}")
            else:
                st.metric("Average Stress Level", "No data")
    else:
        for col in [col1, col2, col3, col4]:
            with col:
                st.metric("No Data", "Run analytics")
    
    # Fetch recent data for charts
    steps_df = get_detailed_metrics('steps', days_back)
    hr_df = get_detailed_metrics('heart_rate', days_back)
    sleep_df = get_detailed_metrics('sleep', days_back)
    
    # Create main charts
    if not steps_df.empty:
        steps_data = steps_df[steps_df['metric_name'] == 'steps']
        if not steps_data.empty:
            # Detect partial days for enhanced visualization
            partial_days = detect_partial_days('steps', days_back)
            
            # Add partial data indicator to the dataframe
            steps_data = steps_data.copy()
            steps_data['is_partial'] = steps_data['date'].isin(partial_days)
            steps_data['data_status'] = steps_data['is_partial'].map({True: 'Partial Data', False: 'Complete Data'})
            
            # Create chart with conditional styling
            fig = go.Figure()
            
            # Add complete data bars
            complete_data = steps_data[~steps_data['is_partial']]
            if not complete_data.empty:
                fig.add_trace(go.Bar(
                    x=complete_data['date'],
                    y=complete_data['value'],
                    name='Complete Data',
                    marker=dict(
                        color='#1f77b4',  # Default blue
                        line=dict(color='#1f77b4', width=1)
                    ),
                    hovertemplate='<b>%{x}</b><br>Steps: %{y:,}<br>Status: Complete Data<extra></extra>'
                ))
            
            # Add partial data bars with enhanced styling
            partial_data = steps_data[steps_data['is_partial']]
            if not partial_data.empty:
                fig.add_trace(go.Bar(
                    x=partial_data['date'],
                    y=partial_data['value'],
                    name='Partial Data',
                    marker=dict(
                        color='rgba(255, 165, 0, 0.6)',  # Orange with transparency
                        line=dict(
                            color='orange', 
                            width=3
                        ),
                        pattern=dict(
                            shape='/',  # Diagonal stripes
                            bgcolor='rgba(255, 255, 255, 0.3)',
                            fgcolor='orange',
                            size=8,
                            solidity=0.3
                        )
                    ),
                    hovertemplate='<b>%{x}</b><br>Steps: %{y:,}<br>Status: <b>Partial Data</b><br><i>Data may be incomplete</i><extra></extra>'
                ))
            
            fig.update_layout(
                title="Daily Steps",
                xaxis_title="Date",
                yaxis_title="Steps",
                showlegend=True,
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Add explanation if there are partial days
            if partial_days:
                st.info(f"⚠️ **Partial data detected** for {len(partial_days)} day(s). These days show orange bars with diagonal stripes and dashed borders to indicate incomplete data.")
        else:
            st.info("No steps data available for the selected time range.")
    
    # Heart rate and sleep charts
    col1, col2 = st.columns(2)
    
    with col1:
        if not hr_df.empty:
            rhr_data = hr_df[hr_df['metric_name'] == 'restingHeartRate']
            if not rhr_data.empty:
                rhr_chart = px.line(
                    rhr_data, 
                    x='date', 
                    y='value',
                    title="Resting Heart Rate",
                    labels={"value": "BPM", "date": "Date"}
                )
                # Set fixed Y-axis range for proper clinical context
                rhr_chart.update_yaxes(range=[1, 100])
                st.plotly_chart(rhr_chart, use_container_width=True)
    
    with col2:
        if not sleep_df.empty:
            sleep_data = sleep_df[sleep_df['metric_name'] == 'sleepTimeSeconds']
            if not sleep_data.empty:
                # Convert seconds to hours
                sleep_data['value'] = sleep_data['value'].astype(float) / 3600
                sleep_chart = px.bar(
                    sleep_data, 
                    x='date', 
                    y='value',
                    title="Sleep Duration",
                    labels={"value": "Hours", "date": "Date"}
                )
                st.plotly_chart(sleep_chart, use_container_width=True)

with tab2:
    st.header("Detailed Metrics")

    metric_types = [
        "Steps", "Heart Rate", "Sleep", "Stress",
        "HRV", "Body Battery", "SpO2", "Respiration"
    ]

    selected_metric = st.selectbox("Select Metric", metric_types)

    # Map selection to data type
    data_type_mapping = {
        "Steps": "steps",
        "Heart Rate": "heart_rate",
        "Sleep": "sleep",
        "Stress": "stress",
        "HRV": "hrv",
        "Body Battery": "body_battery",
        "SpO2": "spo2",
        "Respiration": "respiration"
    }

    selected_data_type = data_type_mapping[selected_metric]

    # Fetch the selected data from detailed metrics
    df = get_detailed_metrics(selected_data_type, days_back)

    if not df.empty:
        # Get unique metrics for this data type
        metrics = df['metric_name'].unique().tolist()
        
        # Filter out useless metrics
        if selected_data_type == 'hrv':
            # Remove non-useful HRV metrics (timestamps, IDs, etc.)
            metrics = [m for m in metrics if not any(
                useless in m.lower() for useless in [
                    'userprofilepk', 'userid', 'id', 'timestamp', 'gmt', 'local'
                ]
            )]
        
        if metrics:
            selected_metrics = st.multiselect(
                "Select Specific Metrics",
                metrics,
                default=metrics[:min(3, len(metrics))]
            )

            if selected_metrics:
                filtered_df = df[df['metric_name'].isin(selected_metrics)]

                # Pivot the data for visualization
                try:
                    # Ensure all values are numeric for aggregation
                    filtered_df = filtered_df.copy()
                    filtered_df['value'] = pd.to_numeric(filtered_df['value'], errors='coerce')
                    
                    # Remove rows with NaN values (non-numeric data)
                    filtered_df = filtered_df.dropna(subset=['value'])
                    
                    if filtered_df.empty:
                        st.warning(f"No numeric data available for {selected_metric}")
                        st.info("Raw data preview:")
                        st.write(df.head())
                    else:
                        pivot_df = filtered_df.pivot_table(
                            index='date',
                            columns='metric_name',
                            values='value',
                            aggfunc='mean'
                        )

                        # Create chart
                        fig = go.Figure()

                        for metric in selected_metrics:
                            if metric in pivot_df.columns:
                                fig.add_trace(go.Scatter(
                                    x=pivot_df.index,
                                    y=pivot_df[metric],
                                    mode='lines+markers',
                                    name=metric
                                ))

                        fig.update_layout(
                            title=f"{selected_metric} Metrics Over Time",
                            xaxis_title="Date",
                            yaxis_title="Value",
                            legend_title="Metrics"
                        )

                        st.plotly_chart(fig, use_container_width=True)

                        # Show the raw data if requested
                        if st.checkbox("Show Raw Data"):
                            st.dataframe(filtered_df)
                except Exception as e:
                    st.error(f"Error creating chart: {e}")
                    st.write("Raw data preview:")
                    st.write(df.head())
            else:
                st.info("Please select at least one metric to display")
        else:
            st.info(f"No metrics found for {selected_metric}")
    else:
        st.info(f"No data available for {selected_metric}")

with tab3:
    st.header("Analytics Insights")
    
    if not analytics_df.empty and 'metrics' in analytics_df.columns:
        metrics = analytics_df['metrics'].iloc[0]
        
        st.subheader("Performance Summary")
        
        # Display calculated metrics
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Activity Metrics")
            metrics_to_show = [
                ('avg_steps', 'Average Steps', ''),
                ('min_steps', 'Minimum Steps', ''),
                ('max_steps', 'Maximum Steps', ''),
                ('total_active_time', 'Total Active Time', 'min'),
            ]
            
            for key, label, unit in metrics_to_show:
                if key in metrics:
                    value = metrics[key]
                    if isinstance(value, (int, float)):
                        if key.startswith('avg_') or key.startswith('min_') or key.startswith('max_'):
                            value = f"{int(value):,}"
                        else:
                            value = f"{value:.1f}"
                    
                    st.metric(label, f"{value} {unit}")
                else:
                    st.metric(label, "No data")
        
        with col2:
            st.subheader("Health Metrics")
            metrics_to_show = [
                ('avg_resting_hr', 'Average Resting HR', 'bpm'),
                ('avg_avg_hrv', 'Average HRV', 'ms'),
                ('avg_sleep_duration', 'Average Sleep', 'hrs'),
                ('avg_avg_stress', 'Average Stress', '')
            ]
            
            for key, label, unit in metrics_to_show:
                if key in metrics:
                    value = metrics[key]
                    if isinstance(value, (int, float)):
                        value = f"{value:.1f}"
                    st.metric(label, f"{value} {unit}")
                else:
                    st.metric(label, "No data")
        
        # Display correlation analysis if available
        if 'correlations' in metrics:
            st.subheader("Correlation Analysis")
            correlations = metrics['correlations']
            
            # Create a heatmap of correlations
            corr_df = pd.DataFrame(correlations)
            
            fig = px.imshow(
                corr_df,
                text_auto=True,
                aspect="auto",
                color_continuous_scale='RdBu_r',
                title="Correlation Between Metrics"
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # List top correlations
            st.subheader("Top Correlations")
            
            # Flatten the correlation matrix
            flat_corr = []
            for i in range(len(corr_df.columns)):
                for j in range(i+1, len(corr_df.columns)):
                    flat_corr.append({
                        'metric1': corr_df.columns[i],
                        'metric2': corr_df.columns[j],
                        'correlation': corr_df.iloc[i, j]
                    })
            
            # Sort by absolute correlation
            flat_corr_df = pd.DataFrame(flat_corr)
            if not flat_corr_df.empty:
                flat_corr_df['abs_corr'] = flat_corr_df['correlation'].abs()
                flat_corr_df = flat_corr_df.sort_values('abs_corr', ascending=False)
                
                # Display top correlations
                st.table(flat_corr_df[['metric1', 'metric2', 'correlation']].head(5))
        
        # Display trend analysis if available
        trend_keys = [k for k in metrics.keys() if k.endswith('_trend') or k.endswith('_pct_change')]
        if trend_keys:
            st.subheader("Trend Analysis")
            
            # Create two columns
            col1, col2 = st.columns(2)
            
            # Show percentage changes
            pct_change_keys = [k for k in metrics.keys() if k.endswith('_pct_change')]
            if pct_change_keys:
                with col1:
                    st.subheader("Metric Changes")
                    
                    # Prepare data for bar chart
                    pct_data = []
                    for key in pct_change_keys:
                        base_metric = key.replace('_pct_change', '')
                        pct_data.append({
                            'Metric': base_metric,
                            'Change %': metrics[key]
                        })
                    
                    pct_df = pd.DataFrame(pct_data)
                    if not pct_df.empty:
                        fig = px.bar(
                            pct_df,
                            x='Metric',
                            y='Change %',
                            title="Percentage Change in Metrics",
                            color='Change %',
                            color_continuous_scale=[(0, "red"), (0.5, "white"), (1, "green")]
                        )
                        st.plotly_chart(fig, use_container_width=True)
            
            # Show trend significance
            trend_keys = [k for k in metrics.keys() if k.endswith('_trend')]
            if trend_keys:
                with col2:
                    st.subheader("Trend Significance")
                    
                    trends_data = []
                    for key in trend_keys:
                        base_metric = key.replace('_trend', '')
                        trend_info = metrics[key]
                        
                        if isinstance(trend_info, dict) and 'slope' in trend_info and 'p_value' in trend_info:
                            trends_data.append({
                                'Metric': base_metric,
                                'Direction': 'Increasing' if trend_info['slope'] > 0 else 'Decreasing',
                                'Significance': 'Significant' if trend_info['p_value'] < 0.05 else 'Not Significant',
                                'p-value': trend_info['p_value'],
                                'r-squared': trend_info.get('r_squared', 0)
                            })
                    
                    trends_df = pd.DataFrame(trends_data)
                    if not trends_df.empty:
                        st.dataframe(trends_df)
    else:
        st.info("No analytics data available. Run the analytics service to generate insights.")

# Footer with refresh info
st.markdown("---")
st.caption(f"Data last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.caption("Biometric Data Interface | © 2025")
