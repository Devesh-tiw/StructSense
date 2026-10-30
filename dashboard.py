import io
import math
import struct
import time
import wave
from collections import deque
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import serial
import serial.tools.list_ports
import streamlit as st

st.set_page_config(
    page_title="StructSense | MPU Bridge Monitor",
    page_icon="🌉",
    layout="wide",
    initial_sidebar_state="expanded",
)

MAX_POINTS = 180


def make_alarm_beep(duration=0.22, frequency=880, sample_rate=22050):
    """Generate a short, self-contained WAV beep for browser playback."""
    frames = bytearray()
    total = int(duration * sample_rate)
    for i in range(total):
        envelope = min(1.0, i / 250, (total - i) / 500)
        sample = int(9000 * envelope * math.sin(2 * math.pi * frequency * i / sample_rate))
        frames.extend(struct.pack("<h", sample))
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return out.getvalue()


ALARM_BEEP = make_alarm_beep()

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.3rem;}
      .status {padding: 0.9rem 1rem; border-radius: 0.7rem; font-weight: 700; font-size: 1.15rem;}
      .safe {background: #064e3b; color: #a7f3d0;}
      .warn {background: #78350f; color: #fde68a;}
      .danger {background: #7f1d1d; color: #fecaca;}
      .muted {color: #94a3b8;}
    </style>
    """,
    unsafe_allow_html=True,
)

# Expected firmware output is either:
#   MPU-only: tilt_deg,vibration_m_s2,gate_closed
#   Legacy:   p1,p2,p3,p4,tilt_deg,vibration_m_s2,gate_closed
# gate_closed is 1 when closed, 0 when open.
if "telemetry" not in st.session_state:
    st.session_state.telemetry = deque(maxlen=MAX_POINTS)
if "last_line" not in st.session_state:
    st.session_state.last_line = "Waiting for ESP32 data"
if "last_received" not in st.session_state:
    st.session_state.last_received = None


@st.cache_resource
def get_serial_connection(port, baud):
    """Keep one serial connection per selected port across Streamlit reruns."""
    return serial.Serial(port=port, baudrate=baud, timeout=0.05)


def parse_line(line):
    """Return tilt, vibration, gate from MPU-only (3-field) or legacy (7-field) CSV."""
    try:
        values = [float(part.strip()) for part in line.split(",")]
    except (TypeError, ValueError):
        return None

    if len(values) == 3:
        tilt, vibration, gate = values
    elif len(values) >= 7:
        # Existing StructSense firmware: p1,p2,p3,p4,tilt,vib_z,gate
        tilt, vibration, gate = values[4], values[5], values[6]
    else:
        return None

    if not all(pd.notna(v) for v in (tilt, vibration, gate)):
        return None
    return float(tilt), float(vibration), int(gate != 0)


def read_available(ser):
    """Read all complete serial lines currently waiting; ignore startup/debug text."""
    received = 0
    while ser.in_waiting:
        raw = ser.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="ignore").strip()
        parsed = parse_line(line)
        if parsed is None:
            continue
        tilt, vibration, gate = parsed
        now = datetime.now()
        st.session_state.telemetry.append(
            {
                "time": now,
                "tilt": tilt,
                "vibration": vibration,
                "gate": gate,
            }
        )
        st.session_state.last_line = line
        st.session_state.last_received = now
        received += 1
    return received


st.title("🌉 StructSense — Bridge Monitor")
st.caption("MPU acceleration and tilt · ESP32-controlled servo barrier and buzzer")

with st.sidebar:
    st.header("Connection")
    detected_ports = [p.device for p in serial.tools.list_ports.comports()]
    fallback_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2", "/dev/ttyACM0"]
    port_options = detected_ports or fallback_ports
    selected_port = st.selectbox("ESP32 serial port", port_options)
    baud = st.selectbox("Baud rate", [115200, 9600], index=0)
    start_stream = st.toggle("Start live stream", value=False)
    sound_enabled = st.checkbox("Enable browser alarm sound", value=True)
    tilt_limit = st.number_input(
        "Tilt alarm limit (degrees)", min_value=0.1, max_value=45.0, value=3.5, step=0.5
    )
    st.caption("Run this dashboard on the same laptop connected to the ESP32 by USB.")
    st.caption("For Linux, the port is usually /dev/ttyUSB0 or /dev/ttyACM0.")
    clear_history = st.button("Clear displayed history")
    if clear_history:
        st.session_state.telemetry.clear()
        st.session_state.last_line = "History cleared"

st.subheader("Live status")
status_area = st.empty()
metric_area = st.container()
chart_area = st.container()


def update_dashboard():
    if start_stream:
        try:
            connection = get_serial_connection(selected_port, baud)
            read_available(connection)
        except (serial.SerialException, OSError) as exc:
            status_area.error(
                f"Cannot open/read {selected_port}: {exc}. Close Arduino Serial Monitor and check the selected port."
            )
            return

    rows = list(st.session_state.telemetry)
    if not rows:
        status_area.info(
            "No valid telemetry received yet. Start the stream, then reset the ESP32. "
            "Expected CSV: tilt,vibration,gate (or the legacy 7-field format)."
        )
        st.caption(f"Latest serial line: {st.session_state.last_line}")
        return

    latest = rows[-1]
    tilt = latest["tilt"]
    vibration = latest["vibration"]
    gate_closed = bool(latest["gate"])
    danger = gate_closed or abs(tilt) >= tilt_limit

    # Play a short browser beep on the alarm edge, then at most every 5 seconds.
    # Browser autoplay policies may require the user to interact with the page first.
    now_epoch = time.time()
    previous_alarm = st.session_state.get("previous_alarm", False)
    last_beep_epoch = st.session_state.get("last_beep_epoch", 0.0)
    if sound_enabled and danger and (not previous_alarm or now_epoch - last_beep_epoch >= 5.0):
        st.audio(ALARM_BEEP, format="audio/wav", autoplay=True)
        st.session_state.last_beep_epoch = now_epoch
    st.session_state.previous_alarm = danger

    if danger:
        status_area.markdown(
            '<div class="status danger">🚨 DANGER — ESP32 reports the barrier closed / tilt alarm</div>',
            unsafe_allow_html=True,
        )
    elif abs(tilt) >= tilt_limit * 0.65:
        status_area.markdown(
            '<div class="status warn">⚠️ WARNING — tilt is approaching the configured limit</div>',
            unsafe_allow_html=True,
        )
    else:
        status_area.markdown(
            '<div class="status safe">✅ NORMAL — no tilt alarm reported</div>',
            unsafe_allow_html=True,
        )

    with metric_area:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Bridge tilt", f"{tilt:.2f}°", help="Tilt value sent by the ESP32 firmware")
        c2.metric("Vertical vibration", f"{vibration:.2f} m/s²")
        c3.metric("Servo barrier", "CLOSED" if gate_closed else "OPEN")
        c4.metric("Samples", str(len(rows)))

    df = pd.DataFrame(rows)
    with chart_area:
        left, right = st.columns(2)
        with left:
            tilt_fig = go.Figure()
            tilt_fig.add_trace(go.Scatter(x=df["time"], y=df["tilt"], name="Tilt", line=dict(color="#a855f7", width=2)))
            tilt_fig.add_hline(y=tilt_limit, line_dash="dash", line_color="#ef4444", annotation_text="Alarm limit")
            tilt_fig.add_hline(y=-tilt_limit, line_dash="dash", line_color="#ef4444")
            tilt_fig.update_layout(title="MPU tilt", yaxis_title="Degrees", height=330, template="plotly_dark", margin=dict(l=15, r=15, t=45, b=15))
            st.plotly_chart(tilt_fig, use_container_width=True)
        with right:
            vibration_fig = go.Figure()
            vibration_fig.add_trace(go.Scatter(x=df["time"], y=df["vibration"], name="Vertical acceleration", line=dict(color="#06b6d4", width=2)))
            vibration_fig.update_layout(title="MPU vertical acceleration / vibration", yaxis_title="m/s²", height=330, template="plotly_dark", margin=dict(l=15, r=15, t=45, b=15))
            st.plotly_chart(vibration_fig, use_container_width=True)

    st.caption(f"Last valid CSV: `{st.session_state.last_line}`")
    st.download_button(
        "Download telemetry CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="structsense_mpu_log.csv",
        mime="text/csv",
    )


# Streamlit fragments refresh only this dashboard section, avoiding the old
# blocking while-loop. On older Streamlit versions, use the manual refresh button.
fragment = getattr(st, "fragment", None)
if fragment is not None:
    fragment(run_every=0.5)(update_dashboard)()
else:
    update_dashboard()
    if start_stream:
        st.warning("For automatic live refresh, upgrade Streamlit: python -m pip install --upgrade streamlit")
        if st.button("Refresh readings"):
            st.rerun()

if st.session_state.last_received is not None:
    st.caption(f"Last valid sample received: {st.session_state.last_received.strftime('%H:%M:%S')}")
