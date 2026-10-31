# StructSense 🌉
**Edge-Processed Multi-Sensor Bridge Failure Detection System**

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-red.svg)
![C++](https://img.shields.io/badge/C++-ESP32-green.svg)


## 📌 Project Overview
StructSense is a real-time, IoT-based Structural Health Monitoring (SHM) prototype designed to prevent highway overpass collapses. Using an ESP32 microcontroller, it captures high-frequency acoustic emissions (micro-cracks) via piezoelectric sensors and low-frequency flexural deflection via an MPU6050 accelerometer. Data is streamed in real-time to a local Python Streamlit digital twin for FFT frequency analysis, wave attenuation mapping, and automated traffic barrier control.

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph Bridge["Smart Highway Overpass"]
        S1["MPU6050 (Tilt & Sway)"]
        Act1["SG90 Servo (Safety Barrier)"]
    end

    S1 --> ESP32["ESP32 DevKit V1"]
    ESP32 --> Act1

    ESP32 -->|Serial USB Data Stream| Laptop["Local Host Dashboard"]

    subgraph Laptop["Python Streamlit Digital Twin"]
        Plotter["Live Telemetry Receiver"]
        Plotter --> GUI["KPI Dashboard & FFT Graph"]
        Plotter --> CSV["Data Logger (.csv)"]
    end
