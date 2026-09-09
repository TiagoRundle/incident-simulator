import streamlit as st
import pandas as pd
import numpy as np
import os
import json
import re
from datetime import datetime, timedelta

st.set_page_config(layout="wide")

st.markdown("""
    <style>
        html, body, [data-testid="stAppViewContainer"] {
            overflow: hidden !important;
            height: 100vh;
        }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Dataset discovery
# -----------------------------------------------------------------------------
# Put this .py file beside one folder per dataset. Each dataset folder may keep
# its CSVs directly inside it or in nested subfolders. Any CSV whose filename
# ends in "_map.csv" is treated as a selectable map/floor. An existing
# "saved_movement.csv" is used for that dataset; otherwise one is created in
# the dataset folder. No paths below need to be edited when datasets are added.

APP_DIR = os.path.dirname(os.path.abspath(__file__))

def pretty_map_name(path):
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r'_map$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_-]+', ' ', name).strip()
    return name.title() or "Main Level"

def discover_datasets(base_dir):
    datasets = {}
    for entry in sorted(os.scandir(base_dir), key=lambda e: e.name.lower()):
        if not entry.is_dir() or entry.name.startswith('.') or entry.name == '__pycache__':
            continue

        map_paths = []
        save_candidates = []
        for root, dirs, files in os.walk(entry.path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            for filename in files:
                lower = filename.lower()
                full_path = os.path.join(root, filename)
                if lower.endswith('_map.csv'):
                    map_paths.append(full_path)
                elif lower == 'saved_movement.csv':
                    save_candidates.append(full_path)

        if not map_paths:
            continue

        map_paths.sort(key=natural_path_sort_key)
        save_file = sorted(save_candidates, key=natural_path_sort_key)[0] if save_candidates else os.path.join(entry.path, 'saved_movement.csv')

        # IMPORTANT: for a multi-floor dataset there is still only ONE
        # saved_movement.csv. Its Level column identifies which map/floor each
        # record belongs to. Whenever possible, use those exact Level values as
        # the map dictionary keys so filtering/playback matches the CSV.
        csv_levels = []
        if os.path.exists(save_file):
            try:
                level_probe = pd.read_csv(save_file, usecols=['Level'])
                csv_levels = [str(v).strip() for v in level_probe['Level'].dropna().unique() if str(v).strip()]
                csv_levels = sorted(csv_levels, key=natural_path_sort_key)
            except (ValueError, pd.errors.EmptyDataError, OSError):
                csv_levels = []

        map_files = {}
        if len(map_paths) > 1 and len(csv_levels) == len(map_paths):
            # Natural-order pairing handles conventions such as floor1/floor2
            # map files with CSV Level values such as 1st Floor/2nd Floor.
            for level_name, path in zip(csv_levels, map_paths):
                map_files[level_name] = path
        else:
            # Fall back to readable names derived from each map filename.
            for path in map_paths:
                label = pretty_map_name(path)
                original_label = label
                suffix = 2
                while label in map_files:
                    label = f"{original_label} ({suffix})"
                    suffix += 1
                map_files[label] = path

        datasets[entry.name] = {
            'root': entry.path,
            'maps': map_files,
            'save_file': save_file,
        }
    return datasets

def natural_path_sort_key(path):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(path))]

DATASETS = discover_datasets(APP_DIR)

if not DATASETS:
    st.error('No datasets found. Add a folder beside this script containing at least one *_map.csv file.')
    st.stop()

dataset_names = list(DATASETS.keys())
selected_dataset = st.sidebar.selectbox('Dataset:', dataset_names, key='selected_dataset')

# When the user switches datasets, discard only the in-memory state so the new
# dataset can load its own CSV. Files on disk are not deleted or overwritten.
if st.session_state.get('_loaded_dataset') != selected_dataset:
    for state_key in ['movement_data', 'active_view_tab', 'session_custom_entities', 'playback_time', 'dataset_start_time', 'dataset_end_time', 'active_sim_floor', 'manual_floor_override']:
        st.session_state.pop(state_key, None)
    st.session_state['_loaded_dataset'] = selected_dataset

dataset_config = DATASETS[selected_dataset]
MAP_FILES = dataset_config['maps']
SAVE_FILE = dataset_config['save_file']

is_multi_floor = len(MAP_FILES) > 1

@st.cache_data
def load_school_map(file_path):
    if os.path.exists(file_path):
        df_map = pd.read_csv(file_path, header=None)
        return df_map.to_numpy().tolist()
    else:
        return np.zeros((30, 30)).tolist()

all_maps_json = {}
map_display_names = {}

if isinstance(MAP_FILES, dict):
    for floor_name, path in MAP_FILES.items():
        all_maps_json[floor_name] = load_school_map(path)

        # Display name comes from the actual map CSV filename.
        display_name = os.path.basename(path)
        display_name = re.sub(r'_map\.csv$', '', display_name, flags=re.IGNORECASE)
        display_name = display_name.replace('_', ' ').strip()
        display_name = ' '.join(
            word[0].upper() + word[1:] if word and word[0].isalpha() else word
            for word in display_name.split()
        )

        map_display_names[floor_name] = display_name

    floor_keys = list(MAP_FILES.keys())
    
    if is_multi_floor:
        # Floor selection is a temporary inspection override while playback is paused.
        # Moving the timeline scrubber (or starting playback in the canvas) returns
        # control of the visual map to the Shooter's Level at that timestamp.
        def mark_manual_floor_override():
            st.session_state.manual_floor_override = True

        if st.session_state.get('active_sim_floor') not in floor_keys:
            st.session_state.active_sim_floor = floor_keys[0]
        if 'manual_floor_override' not in st.session_state:
            st.session_state.manual_floor_override = False

        active_floor = st.sidebar.selectbox(
            "Active Simulation Floor:",
            floor_keys,
            key='active_sim_floor',
            on_change=mark_manual_floor_override,
        )
    else:
        active_floor = floor_keys[0]
        st.session_state.manual_floor_override = False
else:
    active_floor = "Main Level"
    all_maps_json[active_floor] = load_school_map(MAP_FILES)

ACTIVE_GRID = np.array(all_maps_json[active_floor])
GRID_ROWS = ACTIVE_GRID.shape[0]
GRID_COLS = ACTIVE_GRID.shape[1]

default_columns = ['Timestamp', 'Clock Time', 'Entity ID', 'X', 'Y', 'Rounds Fired', 'Status']
if is_multi_floor:
    default_columns.insert(2, 'Level')

if 'movement_data' not in st.session_state:
    if os.path.exists(SAVE_FILE):
        loaded_df = pd.read_csv(SAVE_FILE)
        
        if not is_multi_floor and 'Level' in loaded_df.columns:
            loaded_df = loaded_df.drop(columns=['Level'], errors='ignore')
        elif is_multi_floor and 'Level' not in loaded_df.columns:
            loaded_df['Level'] = active_floor
            
        if 'Entity ID' not in loaded_df.columns:
            loaded_df['Entity ID'] = 'Shooter'
        if 'Rounds Fired' not in loaded_df.columns:
            loaded_df['Rounds Fired'] = 0
        if 'Status' not in loaded_df.columns:
            loaded_df['Status'] = 'Alive'
            
        loaded_df['Rounds Fired'] = loaded_df['Rounds Fired'].fillna(0).astype(int)
        loaded_df['Status'] = loaded_df['Status'].fillna('Alive').astype(str)
        loaded_df['Entity ID'] = loaded_df['Entity ID'].fillna('Shooter').astype(str)
        if is_multi_floor:
            loaded_df['Level'] = loaded_df['Level'].fillna(active_floor).astype(str)
            
        st.session_state.movement_data = loaded_df[default_columns]
    else:
        st.session_state.movement_data = pd.DataFrame(columns=default_columns)

if 'active_view_tab' not in st.session_state:
    st.session_state.active_view_tab = "Shooter"

if 'session_custom_entities' not in st.session_state:
    st.session_state.session_custom_entities = []

if 'playback_time' not in st.session_state:
    st.session_state.playback_time = 0

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

def parse_time_string(time_str):
    try:
        cleaned_str = time_str.strip().upper()
        return datetime.strptime(cleaned_str, "%I:%M:%S %p")
    except ValueError:
        return None

def format_seconds_to_wall_time(base_time_obj, seconds_elapsed):
    if base_time_obj is None:
        return "N/A"
    actual_time = base_time_obj + timedelta(seconds=int(seconds_elapsed))
    return actual_time.strftime("%I:%M:%S %p")

# Infer each dataset's clock window from saved_movement.csv.  The most robust
# source is Clock Time paired with Timestamp: Clock Time - Timestamp gives the
# simulation's base/start time, and max Timestamp gives the natural end time.
def infer_dataset_time_window(movement_df):
    default_start = "9:00:00 AM"
    default_end = "9:00:45 AM"

    if movement_df is None or movement_df.empty:
        return default_start, default_end

    candidates = []
    if 'Clock Time' in movement_df.columns and 'Timestamp' in movement_df.columns:
        for _, row in movement_df[['Clock Time', 'Timestamp']].dropna().iterrows():
            parsed_clock = parse_time_string(str(row['Clock Time']))
            try:
                ts = int(float(row['Timestamp']))
            except (TypeError, ValueError):
                continue
            if parsed_clock is not None:
                candidates.append(parsed_clock - timedelta(seconds=ts))

    if candidates:
        # All correctly formed rows should imply the same base time. Use the
        # most common value so one malformed row does not shift the whole app.
        base_counts = {}
        for candidate in candidates:
            key = candidate.strftime("%I:%M:%S %p")
            base_counts[key] = base_counts.get(key, 0) + 1
        inferred_start = max(base_counts, key=base_counts.get)
        base_obj = parse_time_string(inferred_start)

        numeric_ts = pd.to_numeric(movement_df['Timestamp'], errors='coerce').dropna()
        if base_obj is not None and not numeric_ts.empty:
            inferred_end = format_seconds_to_wall_time(base_obj, int(numeric_ts.max()))
            return inferred_start, inferred_end

    # Fallback for CSVs that have Clock Time but no usable Timestamp pairing.
    if 'Clock Time' in movement_df.columns:
        parsed_times = [parse_time_string(str(v)) for v in movement_df['Clock Time'].dropna()]
        parsed_times = [v for v in parsed_times if v is not None]
        if parsed_times:
            return min(parsed_times).strftime("%I:%M:%S %p"), max(parsed_times).strftime("%I:%M:%S %p")

    return default_start, default_end

inferred_start_time, inferred_end_time = infer_dataset_time_window(st.session_state.movement_data)

if 'dataset_start_time' not in st.session_state:
    st.session_state.dataset_start_time = inferred_start_time
if 'dataset_end_time' not in st.session_state:
    st.session_state.dataset_end_time = inferred_end_time

with st.sidebar.expander("⚙️ Open Global Settings", expanded=False):
    start_time_input = st.text_input(
        "Start Time (HH:MM:SS AM/PM)",
        key="dataset_start_time"
    )
    base_time = parse_time_string(start_time_input)

    end_time_input = st.text_input(
        "End Time (HH:MM:SS AM/PM)",
        key="dataset_end_time"
    )
    end_time = parse_time_string(end_time_input)

    playback_speed = st.selectbox("Playback Speed:", [1, 2, 5, 10], format_func=lambda x: f"{x}x")
    app_layout = st.selectbox("Interface Layout:", ["Horizontal", "Vertical"])

    global_max_seconds = 0
    if base_time and end_time:
        global_max_seconds = int((end_time - base_time).total_seconds())
        if global_max_seconds < 0:
            st.error("⚠️ End time cannot be earlier than start time.")
            global_max_seconds = 0
        else:
            st.caption(f"Duration: `{global_max_seconds}` seconds")

    if not base_time:
        st.error("⚠️ Invalid Start Time Format. Please use 'HH:MM:SS AM/PM'")

st.sidebar.header("Construct Timeline")

existing_entities = ["Shooter"]
if not st.session_state.movement_data.empty:
    file_entities = st.session_state.movement_data['Entity ID'].dropna().astype(str).unique().tolist()
    for ent in file_entities:
        if ent not in existing_entities:
            existing_entities.append(ent)

for custom_ent in st.session_state.session_custom_entities:
    if custom_ent not in existing_entities:
        existing_entities.append(custom_ent)

existing_entities = sorted(existing_entities, key=natural_sort_key)
selected_entity = st.sidebar.selectbox("Record Data For:", existing_entities)

@st.dialog("Create New Simulation Entity")
def unique_entity_creator_modal():
    st.write("Type a unique identifier name below. It will instantly appear as an option in your sidebar dropdown selection list.")
    new_name = st.text_input("Entity Name (e.g. Police 2, Victim 4)", value="").strip()
    
    if st.button("Add to Selection Dropdown"):
        if new_name:
            if new_name not in st.session_state.session_custom_entities and new_name not in existing_entities:
                st.session_state.session_custom_entities.append(new_name)
                st.success(f"'{new_name}' added successfully!")
                st.rerun()
            else:
                st.warning("That entity name already exists.")
        else:
            st.error("Name field cannot be left blank.")

if st.sidebar.button("➕ Add New Entity Option", use_container_width=True):
    unique_entity_creator_modal()

entry_mode = st.sidebar.radio("Time Entry Mode:", ["Clock Time", "Relative Time", "Time Range"])

delta_seconds_list = []
invalid_input = False

if entry_mode == "Clock Time":
    wall_time_entry = st.sidebar.text_input("Clock Time (HH:MM:SS AM/PM)", value=start_time_input)
    target_time = parse_time_string(wall_time_entry)
    if base_time and target_time:
        delta_seconds = int((target_time - base_time).total_seconds())
        if delta_seconds < 0:
            st.sidebar.error("⚠️ Target time cannot be earlier than start time.")
            invalid_input = True
        else:
            delta_seconds_list = [delta_seconds]
    else:
        invalid_input = True
elif entry_mode == "Relative Time":
    relative_entry = st.sidebar.number_input("Seconds In From Start", min_value=0, value=0, step=1)
    delta_seconds = int(relative_entry)
    delta_seconds_list = [delta_seconds]
    if base_time:
        calculated_wall = format_seconds_to_wall_time(base_time, delta_seconds)
        st.sidebar.caption(f"Equivalent Clock Time: `{calculated_wall}`")
elif entry_mode == "Time Range":
    r_col1, r_col2 = st.sidebar.columns(2)
    with r_col1:
        range_start = st.number_input("Start Second", min_value=0, max_value=global_max_seconds, value=0, step=1)
    with r_col2:
        range_end = st.number_input("End Second", min_value=0, max_value=global_max_seconds, value=min(10, global_max_seconds), step=1)
    
    if range_start > range_end:
        st.sidebar.error("⚠️ Start second cannot exceed end second.")
        invalid_input = True
    else:
        delta_seconds_list = list(range(int(range_start), int(range_end) + 1))

st.sidebar.subheader("Coordinates")
x_coord = st.sidebar.number_input(f"Grid X", min_value=-1, max_value=GRID_COLS-1, value=0, step=1)
y_coord = st.sidebar.number_input(f"Grid Y", min_value=-1, max_value=GRID_ROWS-1, value=0, step=1)

with st.sidebar.expander("📝 Open Activity Log", expanded=False):
    rounds_fired_count = st.number_input("Rounds Fired in this Second", min_value=0, max_value=10, value=0, step=1)
    current_status_input = st.radio("Current Medical Status:", ["Alive", "Non-Fatally Injured", "Fatally Injured", "Died"])

def save_and_sort_dataframe(target_sync_time):
    st.session_state.movement_data['sort_key'] = st.session_state.movement_data['Entity ID'].apply(lambda x: tuple(natural_sort_key(x)))
    st.session_state.movement_data = st.session_state.movement_data.sort_values(
        by=['sort_key', 'Timestamp']
    ).drop(columns=['sort_key']).reset_index(drop=True)
    
    st.session_state.movement_data = st.session_state.movement_data[default_columns]
    st.session_state.movement_data.to_csv(SAVE_FILE, index=False)
    st.session_state.active_view_tab = selected_entity
    st.session_state.playback_time = target_sync_time
    st.rerun()

st.sidebar.subheader("Record Modifications")

button_label = "Record Range Rows" if entry_mode == "Time Range" else "Record Single Position Row"

if st.sidebar.button(button_label, use_container_width=True):
    if not selected_entity:
        st.sidebar.error("⚠️ Please specify or select an Entity Name first.")
    elif not base_time:
        st.sidebar.error("⚠️ Fix the Global Start Time before saving.")
    elif invalid_input or not delta_seconds_list:
        st.sidebar.error("⚠️ Invalid Time sequence entry detected.")
    else:
        if not st.session_state.movement_data.empty:
            st.session_state.movement_data = st.session_state.movement_data[
                ~((st.session_state.movement_data['Timestamp'].isin(delta_seconds_list)) & 
                  (st.session_state.movement_data['Entity ID'] == selected_entity))
            ]
        
        new_rows_list = []
        for step_ts in delta_seconds_list:
            clock_time_str = format_seconds_to_wall_time(base_time, step_ts)
            row_dict = {
                'Timestamp': step_ts, 
                'Clock Time': clock_time_str, 
                'Entity ID': selected_entity,
                'X': x_coord, 
                'Y': y_coord,
                'Rounds Fired': int(rounds_fired_count),
                'Status': str(current_status_input)
            }
            if is_multi_floor:
                row_dict['Level'] = active_floor
            new_rows_list.append(row_dict)
            
        if new_rows_list:
            st.session_state.movement_data = pd.concat([st.session_state.movement_data, pd.DataFrame(new_rows_list)], ignore_index=True)
            save_and_sort_dataframe(target_sync_time=delta_seconds_list[-1])

if entry_mode != "Time Range":
    if st.sidebar.button("➡️ Forward to End", use_container_width=True):
        if not selected_entity or not base_time or invalid_input or global_max_seconds == 0:
            st.sidebar.error("⚠️ Verify settings, times, and entities are correct.")
        else:
            if not st.session_state.movement_data.empty:
                st.session_state.movement_data = st.session_state.movement_data[
                    ~((st.session_state.movement_data['Timestamp'] >= delta_seconds) & 
                      (st.session_state.movement_data['Timestamp'] <= global_max_seconds) & 
                      (st.session_state.movement_data['Entity ID'] == selected_entity))
                ]
            
            generated_rows = []
            for t in range(delta_seconds, global_max_seconds + 1):
                row_dict = {
                    'Timestamp': t,
                    'Clock Time': format_seconds_to_wall_time(base_time, t),
                    'Entity ID': selected_entity,
                    'X': x_coord,
                    'Y': y_coord,
                    'Rounds Fired': int(rounds_fired_count),
                    'Status': str(current_status_input)
                }
                if is_multi_floor:
                    row_dict['Level'] = active_floor
                generated_rows.append(row_dict)
            
            if generated_rows:
                st.session_state.movement_data = pd.concat([st.session_state.movement_data, pd.DataFrame(generated_rows)], ignore_index=True)
                save_and_sort_dataframe(target_sync_time=delta_seconds)

    if st.sidebar.button("⬅️ Backward to Start", use_container_width=True):
        if not selected_entity or not base_time or invalid_input:
            st.sidebar.error("⚠️ Verify settings, times, and entities are correct.")
        else:
            if not st.session_state.movement_data.empty:
                st.session_state.movement_data = st.session_state.movement_data[
                    ~((st.session_state.movement_data['Timestamp'] >= 0) & 
                      (st.session_state.movement_data['Timestamp'] <= delta_seconds) & 
                      (st.session_state.movement_data['Entity ID'] == selected_entity))
                ]
            
            generated_rows = []
            for t in range(0, delta_seconds + 1):
                row_dict = {
                    'Timestamp': t,
                    'Clock Time': format_seconds_to_wall_time(base_time, t),
                    'Entity ID': selected_entity,
                    'X': x_coord,
                    'Y': y_coord,
                    'Rounds Fired': int(rounds_fired_count),
                    'Status': str(current_status_input)
                }
                if is_multi_floor:
                    row_dict['Level'] = active_floor
                generated_rows.append(row_dict)
            
            if generated_rows:
                st.session_state.movement_data = pd.concat([st.session_state.movement_data, pd.DataFrame(generated_rows)], ignore_index=True)
                save_and_sort_dataframe(target_sync_time=delta_seconds)

df = st.session_state.movement_data

if global_max_seconds > 0:
    max_time = global_max_seconds
elif not df.empty:
    max_time = int(df['Timestamp'].dropna().max())
    if max_time == 0:
        max_time = 1
else:
    max_time = 1

def render_canvas_workspace(target_time=-1, layout_mode="Vertical"):
    maps_dictionary_json = json.dumps(all_maps_json)
    map_display_names_json = json.dumps(map_display_names)

    route_list = []
    if not df.empty:
        clean_df = df.dropna(subset=["Timestamp", "X", "Y"])
        for item in clean_df.to_dict(orient="records"):
            route_list.append({
                "t": int(item["Timestamp"]),
                "id": str(item["Entity ID"]),
                "floor": str(item.get("Level", active_floor)),
                "x": int(item["X"]),
                "y": int(item["Y"]),
                "count": int(item.get("Rounds Fired", 0)),
                "status": str(item.get("Status", "Alive"))
            })
    route_json = json.dumps(route_list)
    
    start_hour = base_time.hour if base_time else 9
    start_min = base_time.minute if base_time else 40
    start_sec = base_time.second if base_time else 0
    
    max_width_style = "100%" #if layout_mode == "Horizontal" else "700px"
    # Horizontal mode: force every map to fit inside a fixed viewport.
    # Both max-width and max-height are applied, so any rectangular aspect ratio
    # is scaled proportionally without clipping or pushing into the table below.
    if layout_mode == "Horizontal":
        canvas_style = "max-width:100%; max-height:500px; width:auto; height:auto; display:block; margin:0 auto; background-color:#FFFFFF;"
        timeline_control_html = f"""
            <div style="flex:1 1 260px; min-width:140px; max-width:520px; display:flex; align-items:center; padding:0 4px;">
                <input id="timelineSlider" type="range" min="0" max="{max_time}" step="1" value="{max(0, round(target_time))}"
                       style="width:100%; cursor:pointer;" aria-label="Scrub Timeline">
            </div>
        """
        vertical_timeline_html = ""
    else:
        canvas_style = "max-width:100%; max-height:700px; width:auto; height:auto; display:block; margin:0 auto; background-color:#FFFFFF;"
        timeline_control_html = ""
        vertical_timeline_html = f"""
            <div style="width:100%; box-sizing:border-box; padding:8px 4px 0 4px;">
                <input id="timelineSlider" type="range" min="0" max="{max_time}" step="1" value="{max(0, round(target_time))}"
                       style="width:100%; cursor:pointer;" aria-label="Scrub Timeline">
            </div>
        """
    
    html_code = f"""
    <div id="workspaceContainer" style="width:100%; max-width:{max_width_style}; box-sizing:border-box; position:relative; background-color:#F8F9FA; padding:15px; border:1px solid #E0E0E0; border-radius:8px; font-family:sans-serif;">
        
                <div style="background:#FFFFFF; padding:10px; margin-bottom:15px; border-radius:6px; border:1px solid #EAEAEA;">

            <!-- Main control row -->
            <div style="display:flex; align-items:center; gap:12px; flex-wrap:nowrap;">
                <button id="playPauseBtn" style="background-color:#2ECC71; color:white; border:none; padding:8px 16px; font-size:13px; font-weight:bold; border-radius:4px; cursor:pointer; min-width:80px;">▶ Play</button>
                <button id="resetBtn" style="background-color:#95A5A6; color:white; border:none; padding:8px 16px; font-size:13px; font-weight:bold; border-radius:4px; cursor:pointer;">🔄 Reset</button>

                {timeline_control_html}

                <div style="display:flex; gap:15px; margin-left:auto; font-size:14px; font-weight:bold; color:#333333; white-space:nowrap;">
                    <div style="color:#4A4A4A;">🏢 Map: <span id="mapLevelDisplay" style="color:#6c5ce7; font-family:monospace;">{active_floor}</span></div>
                    <div>⏱️ Relative: <span id="timeSec" style="color:#FF4B4B; font-family:monospace;">0.0</span>s</div>
                    <div style="border-left:1px solid #D0D0D0; padding-left:12px;">🕒 Clock: <span id="clockTime" style="color:#0066CC; font-family:monospace;">--:--:-- --</span></div>
                </div>
            </div>

            <!-- Vertical-layout scrubber gets its own row -->
            {vertical_timeline_html}

        </div>

        <div style="position:relative; width:100%; box-sizing:border-box; overflow:hidden; background-color:#CCCCCC; padding:5px; border-radius:4px;">
            <canvas id="mapCanvas" style="{canvas_style}"></canvas>
            <div id="canvas_tooltip" style="position:absolute; display:none; background:#333333; color:#FFFFFF; padding:4px 8px; border-radius:3px; font-size:11px; pointer-events:none; z-index:100; white-space:nowrap;"></div>
        </div>
    </div>
    
    <script>
    (function() {{
        const canvas = document.getElementById('mapCanvas');
        const ctx = canvas.getContext('2d');
        const tooltip = document.getElementById('canvas_tooltip');
        const playPauseBtn = document.getElementById('playPauseBtn');
        const resetBtn = document.getElementById('resetBtn');
        const timelineSlider = document.getElementById('timelineSlider');
        const timeSec = document.getElementById('timeSec');
        const clockTime = document.getElementById('clockTime');
        const mapLevelDisplay = document.getElementById('mapLevelDisplay');
        
        const allFloorMaps = {maps_dictionary_json};
        const mapDisplayNames = {map_display_names_json};
        const route = {route_json};
        
        const bHour = {start_hour};
        const bMin = {start_min};
        const bSec = {start_sec};
        
        const cellSize = 12;
        let isPlaying = false;
        let currentTick = 0;
        let lastFrameTime = null;
        
        const msPerTick = 1000; 
        let maxTime = {max_time};
        let speedMultiplier = {playback_speed};
        
        let currentFloor = "{active_floor}";
        let manualFloorOverride = {str(bool(st.session_state.get('manual_floor_override', False))).lower()};
        
        if ({target_time} >= 0) {{
            currentTick = {target_time};
        }}

        if (window.parent && window.parent.document) {{
            window.parent.document.addEventListener('keydown', handleGlobalKeypress);
        }}
        window.addEventListener('keydown', handleGlobalKeypress);

        function handleGlobalKeypress(e) {{
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {{
                return; 
            }}

            if (e.key === 'ArrowRight') {{
                if (isPlaying) {{
                    isPlaying = false;
                    playPauseBtn.innerText = "▶ Play";
                    playPauseBtn.style.backgroundColor = "#2ECC71";
                    lastFrameTime = null;
                }}
                manualFloorOverride = false;
                currentTick = Math.min(maxTime, Math.floor(currentTick + 1));
                updateDisplay();
                e.preventDefault();
            }} else if (e.key === 'ArrowLeft') {{
                if (isPlaying) {{
                    isPlaying = false;
                    playPauseBtn.innerText = "▶ Play";
                    playPauseBtn.style.backgroundColor = "#2ECC71";
                    lastFrameTime = null;
                }}
                manualFloorOverride = false;
                currentTick = Math.max(0, Math.ceil(currentTick - 1));
                updateDisplay();
                e.preventDefault();
            }}
        }}

        function formatTimeClock(totalSecondsOffset) {{
            let date = new Date();
            date.setHours(bHour, bMin, bSec, 0);
            date.setMilliseconds(date.getMilliseconds() + (totalSecondsOffset * 1000));
            
            let hrs = date.getHours();
            let mins = date.getMinutes();
            let secs = date.getSeconds();
            let ampm = hrs >= 12 ? 'PM' : 'AM';
            
            hrs = hrs % 12;
            hrs = hrs ? hrs : 12;
            
            let strHrs = hrs < 10 ? '0' + hrs : hrs;
            let strMins = mins < 10 ? '0' + mins : mins;
            let strSecs = secs < 10 ? '0' + secs : secs;
            
            return strHrs + ':' + strMins + ':' + strSecs + ' ' + ampm;
        }}

        function drawMap() {{
            const activeMapMatrix = allFloorMaps[currentFloor];
            if (!activeMapMatrix) return;
            
            const rows = activeMapMatrix.length;
            const cols = activeMapMatrix[0].length;
            
            canvas.width = cols * cellSize;
            canvas.height = rows * cellSize;
            
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            for (let y = 0; y < rows; y++) {{
                for (let x = 0; x < cols; x++) {{
                    if (activeMapMatrix[y][x] === 1) {{
                        ctx.fillStyle = '#222222';
                        ctx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize);
                    }} else {{
                        ctx.fillStyle = '#FFFFFF';
                        ctx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize);
                        
                        ctx.strokeStyle = '#EAEAEA';
                        ctx.lineWidth = 0.5;
                        ctx.strokeRect(x * cellSize, y * cellSize, cellSize, cellSize);
                    }}
                }}
            }}
        }}
        
        function drawAgent(id, realX, realY, fraction, shotCount, status) {{
            if (realX < 0 || realY < 0) return;
            const cx = (realX * cellSize) + (cellSize / 2);
            const cz = (realY * cellSize) + (cellSize / 2);
            const radius = (cellSize / 2) * 0.8;
            
            let triggerFlash = false;
            let primaryColor = '#FF4B4B';
            
            let nameLower = id.toLowerCase();
            if (nameLower.includes("police") || nameLower.includes("officer")) {{
                primaryColor = '#0066CC';
            }} else if (nameLower.includes("victim") || nameLower.includes("civilian") || nameLower.includes("bystander")) {{
                primaryColor = '#2ECC71';
            }}
            
            if (status === "Non-Fatally Injured") {{
                primaryColor = '#FFCC00'; 
            }} else if (status === "Fatally Injured") {{
                primaryColor = '#FF8000'; 
            }} else if (status === "Died") {{
                primaryColor = '#000000'; 
            }}
            
            if (shotCount > 0 && status !== "Died") {{
                let interval = 1.0 / shotCount;
                
                for (let i = 0; i < shotCount; i++) {{
                    let shotStartTime = i * interval;
                    let timeSinceShot = fraction - shotStartTime;
                    
                    if (timeSinceShot >= 0 && timeSinceShot < interval) {{
                        let ringDuration = Math.min(0.3, interval); 
                        if (timeSinceShot <= ringDuration) {{
                            let waveProgress = timeSinceShot / ringDuration;
                            let waveRadius = radius + (waveProgress * (cellSize * 1.6));
                            let alpha = 1.0 - waveProgress;
                            
                            ctx.beginPath();
                            ctx.arc(cx, cz, waveRadius, 0, 2 * Math.PI);
                            
                            if (primaryColor === '#0066CC') {{
                                ctx.strokeStyle = 'rgba(0, 102, 204, ' + alpha + ')';
                            }} else {{
                                ctx.strokeStyle = 'rgba(255, 69, 0, ' + alpha + ')';
                            }}
                            ctx.lineWidth = 2.5;
                            ctx.stroke();
                        }}
                        
                        if (timeSinceShot <= Math.min(0.1, interval * 0.4)) {{
                            triggerFlash = true;
                        }}
                    }}
                }}
            }}
            
            ctx.beginPath();
            ctx.arc(cx, cz, radius, 0, 2 * Math.PI);
            
            if (triggerFlash) {{
                ctx.fillStyle = '#FFA500'; 
                ctx.shadowColor = '#FFA500';
                ctx.shadowBlur = 14;
            }} else {{
                ctx.fillStyle = primaryColor;
                ctx.shadowColor = primaryColor;
                ctx.shadowBlur = (primaryColor === '#000000') ? 0 : 6;
            }}
            
            ctx.fill();
            ctx.shadowBlur = 0; 
        }}
        
        function updateDisplay() {{
            let tFloor = Math.floor(currentTick);
            let tCeil = Math.ceil(currentTick);
            let fraction = currentTick - tFloor;
            
            // Normal timeline behavior: follow the Shooter's Level. A sidebar
            // floor selection temporarily overrides this only while inspecting
            // a paused frame. Timeline navigation/playback releases the override.
            if (!manualFloorOverride && route.length > 0) {{
                let shooterTracks = route.filter(r => r.id === "Shooter" && (r.t === tFloor || r.t === tCeil));
                if (shooterTracks.length > 0) {{
                    let shooterTrack = shooterTracks.find(r => r.t === tFloor) || shooterTracks[0];
                    if (shooterTrack.floor && allFloorMaps[shooterTrack.floor]) {{
                        currentFloor = shooterTrack.floor;
                    }}
                }}
            }}
            
            drawMap();
            mapLevelDisplay.innerText = mapDisplayNames[currentFloor] || currentFloor;            
            timeSec.innerText = currentTick.toFixed(1);
            clockTime.innerText = formatTimeClock(currentTick);
            if (timelineSlider) timelineSlider.value = Math.round(currentTick);
            
            if (route.length === 0) return;
            
            let uniqueIds = [];
            route.forEach(r => {{
                if(!uniqueIds.includes(r.id)) uniqueIds.push(r.id);
            }});
            
            uniqueIds.forEach(id => {{
                let agentRows = route.filter(r => r.id === id && r.floor === currentFloor && (r.t === tFloor || r.t === tCeil));
                if (agentRows.length === 0) return;
                
                let p1 = agentRows.find(r => r.t === tFloor);
                let p2 = agentRows.find(r => r.t === tCeil);
                
                if (!p1) p1 = agentRows[0];
                if (!p2) p2 = p1;
                
                let interX, interY;
                
                if (p1.x < 0 || p1.y < 0) {{
                    interX = p2.x;
                    interY = p2.y;
                    if (fraction === 0) return; 
                }} else if (p2.x < 0 || p2.y < 0) {{
                    interX = p1.x;
                    interY = p1.y;
                    if (fraction > 0) return; 
                }} else {{
                    interX = p1.x + (p2.x - p1.x) * fraction;
                    interY = p1.y + (p2.y - p1.y) * fraction;
                }}
                
                drawAgent(id, interX, interY, fraction, p1.count, p1.status);
            }});
        }}
        
        function animationLoop(now) {{
            if (!isPlaying) return;
            if (!lastFrameTime) lastFrameTime = now;
            
            let delta = now - lastFrameTime;
            lastFrameTime = now;
            
            currentTick += (delta / msPerTick) * speedMultiplier;
            
            if (currentTick >= maxTime) {{
                currentTick = maxTime;
                isPlaying = false;
                playPauseBtn.innerText = "▶ Play";
                playPauseBtn.style.backgroundColor = "#2ECC71";
                updateDisplay();
                lastFrameTime = null;
                return;
            }}
            
            updateDisplay();
            requestAnimationFrame(animationLoop);
        }}
        
        playPauseBtn.addEventListener('click', function() {{
            if (route.length === 0) return;
            if (isPlaying) {{
                isPlaying = false;
                playPauseBtn.innerText = "▶ Play";
                playPauseBtn.style.backgroundColor = "#2ECC71";
                lastFrameTime = null;
            }} else {{
                if (currentTick >= maxTime) currentTick = 0;
                manualFloorOverride = false;
                updateDisplay();
                isPlaying = true;
                playPauseBtn.innerText = "⏸ Pause";
                playPauseBtn.style.backgroundColor = "#E67E22";
                lastFrameTime = performance.now();
                requestAnimationFrame(animationLoop);
            }}
        }});
        
        resetBtn.addEventListener('click', function() {{
            isPlaying = false;
            currentTick = 0;
            manualFloorOverride = false;
            lastFrameTime = null;
            playPauseBtn.innerText = "▶ Play";
            playPauseBtn.style.backgroundColor = "#2ECC71";
            updateDisplay();
        }});

        // Integrated scrubber is used by both layouts. Manual scrubbing snaps to
        // whole seconds while playback/currentTick remains sub-second precise.
        if (timelineSlider) {{
            timelineSlider.addEventListener('input', function() {{
                isPlaying = false;
                lastFrameTime = null;
                playPauseBtn.innerText = "▶ Play";
                playPauseBtn.style.backgroundColor = "#2ECC71";
                manualFloorOverride = false;
                currentTick = Math.max(0, Math.min(maxTime, parseFloat(this.value) || 0));
                updateDisplay();
            }});
        }}
        
        updateDisplay();
        
        canvas.addEventListener('mousemove', function(e) {{
            const rect = canvas.getBoundingClientRect();
            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;
            
            const canvasX = (e.clientX - rect.left) * scaleX;
            const canvasY = (e.clientY - rect.top) * scaleY;
            
            const gX = Math.floor(canvasX / cellSize);
            const gY = Math.floor(canvasY / cellSize);
            
            const activeMatrix = allFloorMaps[currentFloor];
            const maxRows = activeMatrix.length;
            const maxCols = activeMatrix[0].length;
            
            if (gX >= 0 && gX < maxCols && gY >= 0 && gY < maxRows) {{
                tooltip.style.display = 'block';
                tooltip.innerText = 'X: ' + gX + ' Y: ' + gY;

                const parentRect = canvas.parentElement.getBoundingClientRect();

                // Tooltip dimensions after it becomes visible
                const tooltipWidth = tooltip.offsetWidth;
                const tooltipHeight = tooltip.offsetHeight;

                const gap = 12;

                // Start by placing tooltip below/right of cursor
                let tooltipX = e.clientX + gap;
                let tooltipY = e.clientY + gap;

                // If it would leave the visible right edge of the canvas,
                // flip it to the left side of the cursor.
                if (tooltipX + tooltipWidth > rect.right) {{
                    tooltipX = e.clientX - tooltipWidth - gap;
                }}

                // If it would leave the visible bottom edge of the canvas,
                // flip it above the cursor.
                if (tooltipY + tooltipHeight > rect.bottom) {{
                    tooltipY = e.clientY - tooltipHeight - gap;
                }}

                // Convert screen coordinates to coordinates inside the map container
                tooltip.style.left = (tooltipX - parentRect.left) + 'px';
                tooltip.style.top = (tooltipY - parentRect.top) + 'px';
            }}
        }});
        
        canvas.addEventListener('mouseleave', function() {{
            tooltip.style.display = 'none';
        }});
    }})();
</script>
"""
    return html_code

def release_manual_floor_override():
    # Timeline navigation takes precedence over a paused manual floor inspection.
    st.session_state.manual_floor_override = False

if app_layout == "Vertical":
    col1, col2 = st.columns([2, 1])
    
    with col2:
        st.subheader("Time-Series Dataset")
        if not df.empty:
            floor_filtered_df = df[df['Level'] == active_floor] if is_multi_floor else df
            clean_entities = floor_filtered_df['Entity ID'].dropna().astype(str).unique()
            available_view_entities = sorted(clean_entities, key=natural_sort_key)
            
            if not available_view_entities:
                st.info(f"No records recorded yet.")
            else:
                if st.session_state.active_view_tab not in available_view_entities:
                    st.session_state.active_view_tab = available_view_entities[0]
                    
                view_filter = st.selectbox("Inspect Sheet View:", available_view_entities, key="active_view_tab")
                display_df = floor_filtered_df[floor_filtered_df['Entity ID'] == view_filter].copy()
                
                st.dataframe(display_df[default_columns], use_container_width=True, height=650, hide_index=True)
        else:
            st.dataframe(df[default_columns], use_container_width=True, height=700, hide_index=True)
            
        current_time = st.session_state.playback_time

    with col1:
        # Vertical layout now uses the same integrated HTML scrubber as horizontal.
        # Extra height accommodates the second toolbar row without clipping the map.
        st.components.v1.html(render_canvas_workspace(target_time=current_time, layout_mode=app_layout), height=GRID_ROWS*12 + 145)

else:
    # Horizontal layout uses the scrubber embedded directly in the map toolbar.
    current_time = st.session_state.playback_time
    st.components.v1.html(render_canvas_workspace(target_time=current_time, layout_mode=app_layout), height=625)

    st.subheader("Time-Series Dataset")
    if not df.empty:
        floor_filtered_df = df[df['Level'] == active_floor] if is_multi_floor else df
        clean_entities = floor_filtered_df['Entity ID'].dropna().astype(str).unique()
        available_view_entities = sorted(clean_entities, key=natural_sort_key)

        if not available_view_entities:
            st.info("No records recorded yet.")
        else:
            if st.session_state.active_view_tab not in available_view_entities:
                st.session_state.active_view_tab = available_view_entities[0]

            view_filter = st.selectbox("Inspect Sheet View:", available_view_entities, key="active_view_tab")
            display_df = floor_filtered_df[floor_filtered_df['Entity ID'] == view_filter].copy()
            st.dataframe(display_df[default_columns], use_container_width=True, height=300, hide_index=True)
    else:
        st.dataframe(df[default_columns], use_container_width=True, height=300, hide_index=True)
