# Garmin Data Project Setup

This project uses the `garminconnect` Python library to access Garmin Connect data from your Garmin device (e.g. Fenix 7).

---

## ✅ Quick Start
1. Environment Variables Setup

  Create a .env file in the project root with your Garmin Connect credentials:

  # GARMIN_EMAIL=your_email@example.com
  # GARMIN_PASSWORD=your_password

  ⚠️ Do not share or commit this file. It contains your login info.

  This file will be automatically loaded when the environment is started.

2. From this project directory, run:

  ```bash
  source ./startup.zsh

