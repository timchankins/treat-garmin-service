#!/bin/bash

# Install tmux if not already installed
if ! command -v tmux &> /dev/null; then
    echo "Installing tmux..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install tmux
    else
        sudo apt-get update && sudo apt-get install -y tmux
    fi
fi

# Create a temporary tmux configuration file
cat > /tmp/tmux_monitor.conf << 'EOF'
# Enable mouse support
set -g mouse on

# Increase scrollback buffer size
set -g history-limit 50000

# Make scrolling with wheels work
set -g terminal-overrides 'xterm*:smcup@:rmcup@'
EOF

# Start a new tmux session with the custom config
tmux -f /tmp/tmux_monitor.conf new-session -d -s garmin-monitor

# Rename the initial window
tmux rename-window -t garmin-monitor:0 'Garmin Monitor'

# Create a layout with multiple panes in a single window
# First split horizontally for the overview section
tmux send-keys -t garmin-monitor:0 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" && echo "" && docker stats' C-m

# Split the window into sections
# Create the main horizontal split
tmux split-window -v -t garmin-monitor:0 -p 80

# Split the bottom section into a 2x3 grid for services
# First horizontal split for the bottom half
tmux split-window -h -t garmin-monitor:0.1

# Split left bottom section vertically in thirds
tmux split-window -v -t garmin-monitor:0.1 -p 66
tmux split-window -v -t garmin-monitor:0.1 -p 50

# Split right bottom section vertically in thirds
tmux split-window -v -t garmin-monitor:0.2 -p 66
tmux split-window -v -t garmin-monitor:0.2 -p 50

# Now we have 7 panes: 1 for overview and 6 for logs

# Send log commands to each pane
# Overview is already set up in pane 0

# Biometric service in pane 1
tmux select-pane -t garmin-monitor:0.1
tmux send-keys "echo 'Biometric Data Service' && docker-compose logs -f biometric_data_service" C-m

# Analytics service in pane 2
tmux select-pane -t garmin-monitor:0.2
tmux send-keys "echo 'Analytics Service' && docker-compose logs -f analytics_service" C-m

# Streamlit in pane 3
tmux select-pane -t garmin-monitor:0.3
tmux send-keys "echo 'Streamlit' && docker-compose logs -f streamlit" C-m

# TimescaleDB in pane 4
tmux select-pane -t garmin-monitor:0.4
tmux send-keys "echo 'TimescaleDB' && docker-compose logs -f timescaledb" C-m

# Postgres in pane 5
tmux select-pane -t garmin-monitor:0.5
tmux send-keys "echo 'Postgres' && docker-compose logs -f postgres" C-m

# Errors in pane 6
tmux select-pane -t garmin-monitor:0.6
tmux send-keys "echo 'Errors' && docker-compose logs -f | grep -i --color 'error\|exception\|fail\|warn'" C-m

# Select the first pane again
tmux select-pane -t garmin-monitor:0.0

# Attach to the session
tmux attach-session -t garmin-monitor

# Clean up the temporary config file
rm /tmp/tmux_monitor.conf
