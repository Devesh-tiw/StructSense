import streamlit as st
import serial
import serial.tools.list_ports
import pandas as pd
import numpy as np
import time
import json
import plotly.graph_objects as go
from collections import deque

st.set_page_config(
    page_title="BridgeGuard | SHM Digital Twin",
    page_icon="🌉",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Dark Industrial Styling
st.markdown("""
<style>
    .status-safe { background-color: #064e3b; color: #34d399; padding: 15px; border-radius: 8px; border-left: 6px solid #10b981; font-weight: bold; font-size: 20px; text-align: center; }
    .status-warn { background-color: #78350f; color: #fbbf24; padding: 15px; border-radius: 8px; border-left: 6px solid #f59e0b; font-weight: bold; font-size: 20px; text-align: center; }
    .status-danger { background-color: #7f1d1d; color: #f87171; padding: 15px; border-radius: 8px; border-left: 6px solid #ef4444; font-weight: bold; font-size: 20px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# Initialize Session State Buffers (Keep last 100 points)
MAX_LEN = 100
if "history" not in st.session_state:
    st.session_state.history = {
        "time": deque(maxlen=MAX_LEN),
        "p1": deque(maxlen=MAX_LEN),
        "p2": deque(maxlen=MAX_LEN),
        "p3": deque(maxlen=MAX_LEN),
        "p4": deque(maxlen=MAX_LEN),
        "tilt": deque(maxlen=MAX_LEN),
        "vib_z": deque(maxlen=MAX_LEN),
        "gate": deque(maxlen=MAX_LEN),
        "health": deque(maxlen=MAX_LEN)
    }
if "csv_log" not in st.session_state:
    st.session_state.csv_log = []

# Sidebar Controls
st.sidebar.title("🌉 BridgeGuard Controls")
mode = st.sidebar.radio("Data Source", ["Demo Simulator (No Hardware Needed)", "Live ESP32 USB Serial (/dev/ttyUSB0)"])

serial_port = "/dev/ttyUSB0"
baud_rate = 115200

if mode == "Live ESP32 USB Serial (/dev/ttyUSB0)":
    ports = [p.device for p in serial.tools.list_ports.comports()]
    serial_port = st.sidebar.selectbox("Select Linux Serial Port", ports if ports else ["/dev/ttyUSB0", "/dev/ttyACM0"])
    baud_rate = st.sidebar.selectbox("Baud Rate", [115200, 9600], index=0)
else:
    st.sidebar.subheader("🧪 Simulator Triggers (For Testing)")
    sim_event = st.sidebar.selectbox(
        "Simulate Bridge Condition:",
        ["Normal Traffic (Safe)", "Tap / Micro-Crack at Node 1", "Crack + Wave Attenuation (Blocked after Node 2)", "Heavy Truck Overload (Bridge Bending)"]
    )

st.sidebar.markdown("---")
tilt_threshold = st.sidebar.slider("Overload Tilt Threshold (°)", 1.0, 10.0, 3.5, 0.5)
piezo_threshold = st.sidebar.slider("Crack Spike Threshold (ADC)", 500, 4095, 1800, 100)

# Header
st.title("🌉 BridgeGuard: IoT Structural Health Monitoring & Digital Twin")
st.caption("Real-Time Piezoelectric Acoustic Emission, MPU6050 Flexural Deflection & Automated Traffic Barrier Control")

# Placeholders for Live Updates
status_placeholder = st.empty()
kpi_cols = st.columns(4)
kpi1 = kpi_cols[0].empty()
kpi2 = kpi_cols[1].empty()
kpi3 = kpi_cols[2].empty()
kpi4 = kpi_cols[3].empty()

chart_cols1 = st.columns(2)
piezo_chart_spot = chart_cols1[0].empty()
mpu_chart_spot = chart_cols1[1].empty()

chart_cols2 = st.columns([2, 1])
fft_chart_spot = chart_cols2[0].empty()
node_map_spot = chart_cols2[1].empty()

# Open Serial if in Live Mode
ser = None
if mode == "Live ESP32 USB Serial (/dev/ttyUSB0)":
    try:
        ser = serial.Serial(serial_port, baud_rate, timeout=0.1)
        st.sidebar.success(f"Connected to {serial_port}")
    except Exception as e:
        st.sidebar.error(f"Cannot open {serial_port}: {e}\nTip: Run 'sudo chmod 666 {serial_port}' in terminal!")

run_live = st.sidebar.checkbox("▶ Start Live Stream", value=True)

# Download CSV Button
if st.session_state.csv_log:
    df_log = pd.DataFrame(st.session_state.csv_log)
    st.sidebar.download_button("📥 Download Telemetry CSV", df_log.to_csv(index=False), "bridgeguard_log.csv", "text/csv")

# Main Telemetry Loop
t_step = 0
while run_live:
    t_step += 1
    now_str = time.strftime("%H:%M:%S")
    
    # 1. GET DATA (Either Simulated or from ESP32 Serial)
    p1, p2, p3, p4, tilt, vib_z, gate = 0, 0, 0, 0, 0.2, 0.0, 0
    
    if mode == "Demo Simulator (No Hardware Needed)":
        base_noise = np.random.randint(40, 120, size=4)
        p1, p2, p3, p4 = base_noise
        tilt = round(0.3 + np.random.normal(0, 0.08), 2)
        vib_z = round(np.random.normal(0, 0.05), 3)
        
        if sim_event == "Tap / Micro-Crack at Node 1":
            # Smooth wave travelling across all 4 nodes
            p1 = int(2400 * np.abs(np.sin(t_step * 0.8)) + np.random.randint(0, 200))
            p2 = int(p1 * 0.85)
            p3 = int(p1 * 0.70)
            p4 = int(p1 * 0.55)
            vib_z = round(np.sin(t_step * 0.8) * 1.5, 2)
        elif sim_event == "Crack + Wave Attenuation (Blocked after Node 2)":
            # Wave spikes at P1 & P2, but dies at P3 & P4 due to structural crack!
            p1 = int(2800 * np.abs(np.sin(t_step * 0.8)) + np.random.randint(0, 200))
            p2 = int(p1 * 0.75)
            p3 = np.random.randint(50, 110)  # Attenuated!
            p4 = np.random.randint(40, 90)   # Attenuated!
            vib_z = round(np.sin(t_step * 0.8) * 2.1, 2)
        elif sim_event == "Heavy Truck Overload (Bridge Bending)":
            tilt = round(5.2 + np.random.normal(0, 0.2), 2)
            vib_z = round(np.sin(t_step * 0.3) * 0.8, 2)
            p1, p2, p3, p4 = np.random.randint(250, 450, size=4) # Low freq rumble
            
    else:
        # Read JSON or CSV line from ESP32: p1,p2,p3,p4,tilt,vib_z,gate
        if ser and ser.in_waiting > 0:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                parts = [float(x) for x in line.split(",")]
                if len(parts) >= 6:
                    p1, p2, p3, p4 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    tilt, vib_z = parts[4], parts[5]
            except:
                pass

    # 2. EVALUATE ALARM & SERVO BARRIER LOGIC
    max_piezo = max(p1, p2, p3, p4)
    wave_drop_ratio = (p3 + p4) / max(1, (p1 + p2))
    
    # Calculate Structural Health Score (0-100%)
    health = 100
    if abs(tilt) >= tilt_threshold:
        health -= 55
    if max_piezo >= piezo_threshold:
        health -= 35
    if p1 > 1200 and wave_drop_ratio < 0.25:
        health -= 40  # Crack attenuation detected!
    health = max(0, min(100, health))

    if abs(tilt) >= tilt_threshold or max_piezo >= piezo_threshold:
        gate = 1 # 1 = CLOSED (Barrier Down)
        status_placeholder.markdown(
            f'<div class="status-danger">🚨 CRITICAL DANGER: STRUCTURAL OVERLOAD / ACOUSTIC CRACK DETECTED — SERVO BARRIER GATE CLOSED (TRAFFIC HALTED)</div>',
            unsafe_allow_html=True
        )
    elif abs(tilt) >= (tilt_threshold * 0.65) or max_piezo >= (piezo_threshold * 0.6):
        gate = 0
        status_placeholder.markdown(
            f'<div class="status-warn">⚠️ WARNING: ELEVATED BRIDGE VIBRATION / HEAVY VEHICLE LOAD DETECTED</div>',
            unsafe_allow_html=True
        )
    else:
        gate = 0
        status_placeholder.markdown(
            f'<div class="status-safe">✅ BRIDGE STATUS: SAFE & OPERATIONAL — ALL NODES NORMAL — BARRIER GATE OPEN</div>',
            unsafe_allow_html=True
        )

    # Save to buffers
    H = st.session_state.history
    H["time"].append(now_str)
    H["p1"].append(p1); H["p2"].append(p2); H["p3"].append(p3); H["p4"].append(p4)
    H["tilt"].append(tilt); H["vib_z"].append(vib_z); H["gate"].append(gate); H["health"].append(health)
    
    st.session_state.csv_log.append({
        "Timestamp": now_str, "Piezo1": p1, "Piezo2": p2, "Piezo3": p3, "Piezo4": p4,
        "Tilt_Deg": tilt, "Vibration_Z": vib_z, "Barrier_Closed": gate, "Health_Index": health
    })

    # 3. UPDATE KPI CARDS
    kpi1.metric("Bridge Mid-Span Tilt (MPU6050)", f"{tilt:.2f}°", f"{tilt - 0.3:.2f}° vs baseline", delta_color="inverse")
    kpi2.metric("Peak Acoustic Spike (Piezos)", f"{max_piezo} ADC", "High-Freq Crack Check")
    kpi3.metric("Automated Servo Barrier", "CLOSED (0° - Blocked)" if gate else "OPEN (90° - Clear)", " Emergency Halt" if gate else "Normal Flow", delta_color="off")
    kpi4.metric("Structural Health Index", f"{health}%", f"{health - 100}%", delta_color="normal")

    # 4. PLOT 1: 4-Channel Piezo Acoustic Wave Propagation
    fig_piezo = go.Figure()
    fig_piezo.add_trace(go.Scatter(y=list(H["p1"]), name="Node 1 (Left Span)", line=dict(color="#ef4444", width=2)))
    fig_piezo.add_trace(go.Scatter(y=list(H["p2"]), name="Node 2 (Mid-Left)", line=dict(color="#f59e0b", width=2)))
    fig_piezo.add_trace(go.Scatter(y=list(H["p3"]), name="Node 3 (Mid-Right)", line=dict(color="#3b82f6", width=2)))
    fig_piezo.add_trace(go.Scatter(y=list(H["p4"]), name="Node 4 (Right Span)", line=dict(color="#10b981", width=2)))
    fig_piezo.add_hline(y=piezo_threshold, line_dash="dash", line_color="red", annotation_text="Crack Threshold")
    fig_piezo.update_layout(title="4x Piezo Discs: Acoustic Wave Propagation & Crack Attenuation", height=320, margin=dict(l=20,r=20,t=40,b=20), template="plotly_dark", yaxis_range=[0, 4200])
    piezo_chart_spot.plotly_chart(fig_piezo, use_container_width=True, key=f"piezo_{t_step}")

    # 5. PLOT 2: MPU6050 Flexural Deflection (Tilt & Z-Vibration)
    fig_mpu = go.Figure()
    fig_mpu.add_trace(go.Scatter(y=list(H["tilt"]), name="Deck Tilt Angle (°)", line=dict(color="#a855f7", width=3)))
    fig_mpu.add_trace(go.Scatter(y=list(H["vib_z"]), name="Vertical Sway Accel (g)", line=dict(color="#06b6d4", width=2, dash="dot")))
    fig_mpu.add_hline(y=tilt_threshold, line_dash="dash", line_color="orange", annotation_text="Max Safe Sag")
    fig_mpu.update_layout(title="MPU6050: Mid-Span Bending & Flexural Vibration", height=320, margin=dict(l=20,r=20,t=40,b=20), template="plotly_dark", yaxis_range=[-4, 8])
    mpu_chart_spot.plotly_chart(fig_mpu, use_container_width=True, key=f"mpu_{t_step}")

    # 6. PLOT 3: Live FFT Frequency Spectrum (Truck Rumble vs. Crack Snap)
    if len(H["p1"]) >= 16:
        sig = np.array(list(H["p1"])) - np.mean(H["p1"])
        fft_vals = np.abs(np.fft.rfft(sig))
        fft_freqs = np.fft.rfftfreq(len(sig), d=0.1) * 100 # Scaled to Hz representation
        fig_fft = go.Figure()
        fig_fft.add_trace(go.Bar(x=fft_freqs, y=fft_vals, marker_color="#ec4899", name="Spectral Energy"))
        fig_fft.add_vrect(x0=0, x1=120, fillcolor="green", opacity=0.15, annotation_text="Low-Freq Truck Rumble (Ignored)")
        fig_fft.add_vrect(x0=120, x1=500, fillcolor="red", opacity=0.15, annotation_text="High-Freq Crack Acoustic Zone")
        fig_fft.update_layout(title="FFT Frequency Filter (Separating Heavy Truck Noise from Micro-Cracks)", xaxis_title="Frequency (Hz)", yaxis_title="Magnitude", height=280, margin=dict(l=20,r=20,t=40,b=20), template="plotly_dark")
        fft_chart_spot.plotly_chart(fig_fft, use_container_width=True, key=f"fft_{t_step}")

    # 7. NODE ENERGY MAP (Visualizing Wave Attenuation across the Bridge)
    fig_nodes = go.Figure(go.Bar(
        x=["Piezo 1\n(0.15m)", "Piezo 2\n(0.30m)", "Piezo 3\n(0.45m)", "Piezo 4\n(0.60m)"],
        y=[p1, p2, p3, p4],
        marker_color=["#ef4444", "#f59e0b", "#3b82f6", "#10b981"]
    ))
    fig_nodes.update_layout(title="Live Span Energy Distribution", yaxis_range=[0, 4095], height=280, margin=dict(l=20,r=20,t=40,b=20), template="plotly_dark")
    node_map_spot.plotly_chart(fig_nodes, use_container_width=True, key=f"node_{t_step}")

    time.sleep(0.15)