# import os
# import json
# import datetime
# import hashlib
# import colorsys
# from flask import Flask, request, jsonify, send_file
# from flask_cors import CORS
# from werkzeug.utils import secure_filename
# import time
# import threading
# import sys
# from collections import deque
# import base64
# import psycopg2
# import psycopg2.extras

# app = Flask(__name__)
# CORS(app, origins='*')

# # ======================== CONFIGURATION ========================
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
# METADATA_FOLDER = os.path.join(BASE_DIR, 'metadata')
# OPERATIONS_FOLDER = os.path.join(BASE_DIR, 'operations')
# LIVE_DATA_FILE = os.path.join(BASE_DIR, 'live_data.json')
# RECEIVED_IMAGES_FILE = os.path.join(BASE_DIR, 'received_images.json')
# ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# # Create folders if they don't exist
# try:
#     os.makedirs(UPLOAD_FOLDER, exist_ok=True)
#     os.makedirs(METADATA_FOLDER, exist_ok=True)
#     os.makedirs(OPERATIONS_FOLDER, exist_ok=True)
#     print(f"✅ Upload folder: {UPLOAD_FOLDER}")
#     print(f"✅ Metadata folder: {METADATA_FOLDER}")
#     print(f"✅ Operations folder: {OPERATIONS_FOLDER}")
# except Exception as e:
#     print(f"❌ Error creating folders: {e}")

# # ======================== AUTH / POSTGRES CONFIGURATION ========================
# DATABASE_URL = os.environ.get('DATABASE_URL', '')
# # Render (and some other hosts) hand out "postgres://..." but psycopg2's
# # newer versions want "postgresql://..." — normalize it either way.
# if DATABASE_URL.startswith('postgres://'):
#     DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# # TEMPORARY: fixed OTP for every login attempt. Replace this with a real
# # SMS/email OTP provider (Twilio, SES, etc.) later — search for TEMP_OTP
# # in this file when you're ready to wire that in.
# TEMP_OTP = '1234'

# # "login data will static" — same 4 accounts from the old Flutter
# # AuthService, now seeded into Postgres once on first startup.
# STATIC_USERS = [
#     {'email': 'superadmin@system.com', 'password': 'securepass', 'displayName': 'System Admin', 'role': 'superadmin'},
#     {'email': 'company@company.com', 'password': 'securepass', 'displayName': 'Company Admin', 'role': 'companyadmin'},
#     {'email': 'controller@drone.com', 'password': 'securepass', 'displayName': 'Drone Controller', 'role': 'controller'},
#     {'email': 'user@drone.com', 'password': 'securepass', 'displayName': 'Regular User', 'role': 'user'},
# ]

# # ======================== LIVE DATA STORAGE (LEGACY) ========================
# # Kept for backward compatibility / the old single-point endpoints.
# # New work should use the Operations system below.
# MAX_LIVE_DATA_POINTS = 1000
# live_data_store = deque(maxlen=MAX_LIVE_DATA_POINTS)
# live_data_lock = threading.Lock()

# latest_drone_position = {
#     'latitude': None,
#     'longitude': None,
#     'altitude': None,
#     'distance': None,
#     'compass': None,
#     'timestamp': None,
#     'droneType': None,
#     'status': 'idle'
# }

# # ======================== RECEIVED IMAGES STORAGE (LEGACY) ========================
# received_images = []
# received_images_lock = threading.Lock()
# MAX_RECEIVED_IMAGES = 500

# # ======================== LIVE OPERATIONS STORAGE ========================
# #
# # An "operation" is one Live -> Stop session on the app. Each operation:
# #   - gets a unique operationId and an assigned color (stable per-user hue,
# #     shifted lightness per session so the same user's Nth session looks
# #     different from their 1st)
# #   - is persisted as its own JSON file under /operations/<operationId>.json
# #   - has its captured photos saved under /uploads/<operationId>/wp_<n>.jpg,
# #     with each point's `imageUrl` pointing at its own photo
# #
# # active_operations mirrors in-memory state for operations currently being
# # written to; completed/older operations are read straight from disk.

# operations_lock = threading.Lock()
# active_operations = {}  # operation_id -> dict

# # Distinct lightness steps so the SAME user's different sessions are
# # visibly different shades of their own hue, not randomly re-picked colors.
# _LIGHTNESS_STEPS = [55, 38, 70, 30, 82, 46, 64, 25]


# def _cors_ok():
#     r = jsonify({'status': 'ok'})
#     r.headers.add('Access-Control-Allow-Origin', '*')
#     r.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, DELETE')
#     r.headers.add('Access-Control-Allow-Headers', 'Content-Type')
#     return r


# def operation_file_path(op_id):
#     return os.path.join(OPERATIONS_FOLDER, f'{secure_filename(op_id)}.json')


# def save_operation(op):
#     try:
#         with open(operation_file_path(op['operationId']), 'w') as f:
#             json.dump(op, f, indent=2)
#     except Exception as e:
#         print(f"❌ Error saving operation {op.get('operationId')}: {e}")


# def load_operation_from_disk(op_id):
#     path = operation_file_path(op_id)
#     if not os.path.exists(path):
#         return None
#     try:
#         with open(path) as f:
#             return json.load(f)
#     except Exception as e:
#         print(f"❌ Error loading operation {op_id}: {e}")
#         return None


# def get_operation(op_id):
#     """Get from memory, falling back to disk (covers server restarts)."""
#     op = active_operations.get(op_id)
#     if op is None:
#         op = load_operation_from_disk(op_id)
#         if op is not None:
#             active_operations[op_id] = op
#     return op


# def count_user_operations(username):
#     count = 0
#     if not os.path.exists(OPERATIONS_FOLDER):
#         return 0
#     for fname in os.listdir(OPERATIONS_FOLDER):
#         if not fname.endswith('.json'):
#             continue
#         try:
#             with open(os.path.join(OPERATIONS_FOLDER, fname)) as f:
#                 if json.load(f).get('username') == username:
#                     count += 1
#         except Exception:
#             pass
#     return count


# def assign_operation_color(username, op_index_for_user):
#     """Stable hue per username (so a user is always roughly the same
#     color family), distinct lightness per operation index (so session #1
#     vs session #2 for the same user are visibly different shades)."""
#     hue = int(hashlib.md5(username.encode()).hexdigest(), 16) % 360
#     lightness = _LIGHTNESS_STEPS[op_index_for_user % len(_LIGHTNESS_STEPS)]
#     r, g, b = colorsys.hls_to_rgb(hue / 360, lightness / 100, 0.65)
#     return '#{:02X}{:02X}{:02X}'.format(int(r * 255), int(g * 255), int(b * 255))


# def stale_active_operation_sweeper():
#     """Background thread: auto-closes operations that have gone silent
#     for too long (e.g. app crashed mid-stream without hitting Stop),
#     so they don't sit as 'active' forever."""
#     STALE_AFTER_SECONDS = 180  # 3 minutes with no new point
#     while True:
#         time.sleep(60)
#         try:
#             now = datetime.datetime.now()
#             with operations_lock:
#                 stale_ids = []
#                 for op_id, op in list(active_operations.items()):
#                     if op.get('status') != 'active':
#                         continue
#                     last_ts_str = None
#                     if op.get('points'):
#                         last_ts_str = op['points'][-1].get('timestamp')
#                     else:
#                         last_ts_str = op.get('startTime')
#                     if not last_ts_str:
#                         continue
#                     try:
#                         last_ts = datetime.datetime.fromisoformat(last_ts_str)
#                     except Exception:
#                         continue
#                     if (now - last_ts).total_seconds() > STALE_AFTER_SECONDS:
#                         stale_ids.append(op_id)

#                 for op_id in stale_ids:
#                     op = active_operations[op_id]
#                     op['status'] = 'completed'
#                     op['endTime'] = now.isoformat()
#                     op['autoClosedReason'] = 'stale_no_activity'
#                     save_operation(op)
#                     active_operations.pop(op_id, None)
#                     print(f"⚠️ Auto-closed stale operation: {op_id}")
#         except Exception as e:
#             print(f"❌ Stale sweeper error: {e}")


# # ======================== HELPERS ========================
# def allowed_file(filename):
#     return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# def save_metadata(metadata, filename):
#     """Save metadata as JSON file"""
#     try:
#         base_name = filename.rsplit('.', 1)[0]
#         metadata_path = os.path.join(METADATA_FOLDER, f"{base_name}.json")
#         with open(metadata_path, 'w') as f:
#             json.dump(metadata, f, indent=2)
#         return metadata_path
#     except Exception as e:
#         print(f"❌ Error saving metadata: {e}")
#         return None


# def save_live_data_to_file():
#     """Save legacy live data to file for persistence"""
#     try:
#         with live_data_lock:
#             data_to_save = {
#                 'timestamp': datetime.datetime.now().isoformat(),
#                 'latest_position': latest_drone_position,
#                 'history': list(live_data_store)
#             }
#         with open(LIVE_DATA_FILE, 'w') as f:
#             json.dump(data_to_save, f, indent=2)
#     except Exception as e:
#         print(f"❌ Error saving live data: {e}")


# def save_received_images_to_file():
#     """Save received images to file for persistence"""
#     try:
#         with received_images_lock:
#             data_to_save = {
#                 'timestamp': datetime.datetime.now().isoformat(),
#                 'images': received_images
#             }
#         with open(RECEIVED_IMAGES_FILE, 'w') as f:
#             json.dump(data_to_save, f, indent=2)
#     except Exception as e:
#         print(f"❌ Error saving received images: {e}")


# def load_live_data_from_file():
#     """Load legacy live data from file on startup"""
#     global latest_drone_position, live_data_store
#     try:
#         if os.path.exists(LIVE_DATA_FILE):
#             with open(LIVE_DATA_FILE, 'r') as f:
#                 data = json.load(f)
#                 if 'latest_position' in data:
#                     latest_drone_position = data['latest_position']
#                 if 'history' in data:
#                     live_data_store.extend(data['history'])
#             print(f"✅ Loaded {len(live_data_store)} live data points")
#     except Exception as e:
#         print(f"❌ Error loading live data: {e}")


# def load_received_images_from_file():
#     """Load received images from file on startup"""
#     global received_images
#     try:
#         if os.path.exists(RECEIVED_IMAGES_FILE):
#             with open(RECEIVED_IMAGES_FILE, 'r') as f:
#                 data = json.load(f)
#                 if 'images' in data:
#                     received_images = data['images']
#             print(f"✅ Loaded {len(received_images)} received images")
#     except Exception as e:
#         print(f"❌ Error loading received images: {e}")


# # ======================== AUTH HELPERS (POSTGRES) ========================

# def get_db():
#     """One connection per request — fine at this traffic level with a
#     single gunicorn worker. Swap for a connection pool later if needed."""
#     return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


# def init_auth_db():
#     """Creates the users table if missing and seeds the static accounts
#     exactly once. Safe to call on every startup."""
#     if not DATABASE_URL:
#         print('⚠️ DATABASE_URL not set — /api/auth/* routes will fail until you add it on Render')
#         return
#     try:
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute('''
#             CREATE TABLE IF NOT EXISTS users (
#                 id SERIAL PRIMARY KEY,
#                 email VARCHAR(255) UNIQUE NOT NULL,
#                 password VARCHAR(255),
#                 display_name VARCHAR(255),
#                 role VARCHAR(50) NOT NULL DEFAULT 'user',
#                 created_at TIMESTAMP DEFAULT NOW(),
#                 last_login TIMESTAMP
#             )
#         ''')
#         conn.commit()

#         # Device-lock column. IF NOT EXISTS makes this safe to run against a
#         # users table that already existed before this feature was added —
#         # no separate manual migration step needed.
#         cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS device_id VARCHAR(255)')
#         conn.commit()

#         cur.execute('SELECT COUNT(*) AS count FROM users')
#         count = cur.fetchone()['count']
#         if count == 0:
#             for u in STATIC_USERS:
#                 cur.execute(
#                     'INSERT INTO users (email, password, display_name, role) '
#                     'VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING',
#                     (u['email'], u['password'], u['displayName'], u['role'])
#                 )
#             conn.commit()
#             print(f'✅ Seeded {len(STATIC_USERS)} static users into Postgres')
#         else:
#             print(f'✅ Users table already has {count} row(s)')

#         cur.close()
#         conn.close()
#     except Exception as e:
#         print(f'❌ init_auth_db error: {e}')


# # ======================== API ENDPOINTS ========================

# # ======================== 1. UPLOAD IMAGE (From Drone Ranger) ========================

# @app.route('/api/upload_drone_image', methods=['POST', 'OPTIONS'])
# def upload_drone_image():
#     """Upload image with metadata from Drone Ranger"""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     try:
#         print("=" * 50)
#         print("📸 Upload request received")
#         print(f"Files: {request.files.keys()}")
#         print(f"Form data: {request.form.keys()}")

#         if 'image' not in request.files:
#             return jsonify({'error': 'No image file provided'}), 400

#         file = request.files['image']

#         if file.filename == '':
#             return jsonify({'error': 'No image selected'}), 400

#         if file and allowed_file(file.filename):
#             timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
#             original_filename = secure_filename(file.filename)
#             extension = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'jpg'
#             filename = f"drone_{timestamp}.{extension}"
#             filepath = os.path.join(UPLOAD_FOLDER, filename)

#             file.save(filepath)
#             print(f"✅ Image saved: {filepath}")

#             user_id = request.form.get('userId', 'unknown')
#             username = request.form.get('username', 'Unknown')
#             user_email = request.form.get('userEmail', '')
#             is_admin = request.form.get('isAdmin', 'false').lower() == 'true'

#             metadata = {
#                 'pitch': request.form.get('pitch', '0.0'),
#                 'roll': request.form.get('roll', '0.0'),
#                 'compass': request.form.get('compass', '0.0'),
#                 'distance': request.form.get('distance', '0.0'),
#                 'latitude': request.form.get('latitude', 'N/A'),
#                 'longitude': request.form.get('longitude', 'N/A'),
#                 'timestamp': request.form.get('timestamp', datetime.datetime.now().isoformat()),
#                 'zoomLevel': request.form.get('zoomLevel', '1.0'),
#                 'boxSize': request.form.get('boxSize', '0'),
#                 'imageIndex': request.form.get('imageIndex', '0'),
#                 'imageName': filename,
#                 'uploadedAt': datetime.datetime.now().isoformat(),
#                 'status': 'received',
#                 'uploadedBy': username,
#                 'userId': user_id,
#                 'username': username,
#                 'userEmail': user_email,
#                 'isAdmin': is_admin,
#                 'source': 'drone_ranger'
#             }

#             save_metadata(metadata, filename)
#             print(f"✅ Metadata saved for user: {username}")

#             return jsonify({
#                 'success': True,
#                 'message': 'Image uploaded successfully',
#                 'filename': filename,
#                 'metadata': metadata
#             }), 201

#         else:
#             return jsonify({'error': 'Invalid file type. Allowed: png, jpg, jpeg, gif'}), 400

#     except Exception as e:
#         print(f"❌ Upload error: {str(e)}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({'error': str(e)}), 500


# # ======================== 2. SEND DRONE DATA (Legacy — single photo_data send) ========================

# @app.route('/api/send_drone_data', methods=['POST', 'OPTIONS'])
# def send_drone_data():
#     """Receive one-off drone data from mobile app (manual capture flow, not streaming)"""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     try:
#         data = request.get_json()
#         if not data:
#             return jsonify({'error': 'No data provided'}), 400

#         print("📡 Live data received:")
#         print(f"  User: {data.get('username', 'Unknown')}")
#         print(f"  Distance: {data.get('distance', 'N/A')}m")
#         print(f"  Altitude: {data.get('altitude', 'N/A')}m")
#         print(f"  Compass: {data.get('compass', 'N/A')}°")
#         print(f"  Drone Size: {data.get('droneSize', 'N/A')}cm")

#         user_id = data.get('userId', 'unknown')
#         username = data.get('username', 'Unknown')
#         user_email = data.get('userEmail', '')
#         is_admin = data.get('isAdmin', False)

#         live_data_point = {
#             'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
#             'pitch': float(data.get('pitch', 0)),
#             'roll': float(data.get('roll', 0)),
#             'compass': float(data.get('compass', 0)),
#             'distance': float(data.get('distance', 0)),
#             'horizontalDistance': float(data.get('horizontalDistance', 0)),
#             'altitude': float(data.get('altitude', 0)),
#             'latitude': data.get('latitude', 'N/A'),
#             'longitude': data.get('longitude', 'N/A'),
#             'zoomLevel': float(data.get('zoomLevel', 1.0)),
#             'boxSize': float(data.get('boxSize', 0)),
#             'droneSize': float(data.get('droneSize', 15.0)),
#             'droneCategory': data.get('droneCategory', 'Custom'),
#             'isCalibrated': data.get('isCalibrated', False),
#             'calibrationPoints': int(data.get('calibrationPoints', 0)),
#             'status': 'active',
#             'userId': user_id,
#             'username': username,
#             'userEmail': user_email,
#             'isAdmin': is_admin,
#             'dataType': data.get('dataType', 'photo_data')
#         }

#         with live_data_lock:
#             live_data_store.append(live_data_point)
#             latest_drone_position.update({
#                 'latitude': data.get('latitude', 'N/A'),
#                 'longitude': data.get('longitude', 'N/A'),
#                 'altitude': data.get('altitude', 0),
#                 'distance': data.get('distance', 0),
#                 'compass': data.get('compass', 0),
#                 'droneSize': data.get('droneSize', 15.0),
#                 'droneCategory': data.get('droneCategory', 'Custom'),
#                 'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
#                 'status': 'active',
#                 'userId': user_id,
#                 'username': username
#             })

#         threading.Thread(target=save_live_data_to_file).start()

#         return jsonify({
#             'success': True,
#             'message': 'Data received successfully',
#             'data_received': True,
#             'total_points': len(live_data_store)
#         }), 200

#     except Exception as e:
#         print(f"❌ Send data error: {str(e)}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({'error': str(e)}), 500


# # ======================== 3. SEND LIVE DATA (Legacy fallback — used only when no operation is active) ========================

# @app.route('/api/send_live_data', methods=['POST', 'OPTIONS'])
# def send_live_data():
#     """Legacy single live-data send to admin. The Flutter app now uses the
#     Operations endpoints below for streaming; this route stays as a fallback
#     for the manual 'Send Single Live Data' admin button when no Live
#     operation is currently open."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     try:
#         data = request.get_json()
#         if not data:
#             return jsonify({'error': 'No data provided'}), 400

#         print("📡 Live data sent to Admin (legacy path):")
#         print(f"  User: {data.get('username', 'Unknown')}")
#         print(f"  Distance: {data.get('distance', 'N/A')}m")
#         print(f"  Altitude: {data.get('altitude', 'N/A')}m")

#         user_id = data.get('userId', 'unknown')
#         username = data.get('username', 'Unknown')
#         user_email = data.get('userEmail', '')
#         is_admin = data.get('isAdmin', False)

#         live_data_point = {
#             'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
#             'pitch': float(data.get('pitch', 0)),
#             'roll': float(data.get('roll', 0)),
#             'compass': float(data.get('compass', 0)),
#             'distance': float(data.get('distance', 0)),
#             'horizontalDistance': float(data.get('horizontalDistance', 0)),
#             'altitude': float(data.get('altitude', 0)),
#             'user_latitude': data.get('user_latitude', 'N/A'),
#             'user_longitude': data.get('user_longitude', 'N/A'),
#             'drone_latitude': data.get('drone_latitude', 'N/A'),
#             'drone_longitude': data.get('drone_longitude', 'N/A'),
#             'zoomLevel': float(data.get('zoomLevel', 1.0)),
#             'boxSize': float(data.get('boxSize', 0)),
#             'droneSize': float(data.get('droneSize', 15.0)),
#             'droneCategory': data.get('droneCategory', 'Custom'),
#             'activeMode': data.get('activeMode', 'Unknown'),
#             'activeModeName': data.get('activeModeName', 'Unknown'),
#             'activeModeIcon': data.get('activeModeIcon', '📐'),
#             'isCalibrated': data.get('activeModeCalibrated', False),
#             'calibrationPoints': int(data.get('activeModePoints', 0)),
#             'userId': user_id,
#             'username': username,
#             'userEmail': user_email,
#             'isAdmin': is_admin,
#             'isContinuous': data.get('isContinuous', False),
#             'sessionId': data.get('sessionId', ''),
#             'sequenceNumber': data.get('sequenceNumber', 0),
#             'hasDronePosition': data.get('hasDronePosition', False),
#             'bearing': float(data.get('bearing', 0)),
#             'dataType': 'live_data'
#         }

#         with live_data_lock:
#             live_data_store.append(live_data_point)
#             latest_drone_position.update({
#                 'latitude': data.get('drone_latitude', 'N/A'),
#                 'longitude': data.get('drone_longitude', 'N/A'),
#                 'altitude': data.get('altitude', 0),
#                 'distance': data.get('distance', 0),
#                 'compass': data.get('compass', 0),
#                 'droneSize': data.get('droneSize', 15.0),
#                 'droneCategory': data.get('droneCategory', 'Custom'),
#                 'activeMode': data.get('activeModeName', 'Unknown'),
#                 'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
#                 'status': 'active',
#                 'userId': user_id,
#                 'username': username,
#                 'userLat': data.get('user_latitude', 'N/A'),
#                 'userLng': data.get('user_longitude', 'N/A')
#             })

#         threading.Thread(target=save_live_data_to_file).start()

#         return jsonify({
#             'success': True,
#             'message': 'Live data sent to admin',
#             'total_points': len(live_data_store)
#         }), 200

#     except Exception as e:
#         print(f"❌ Send live data error: {str(e)}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({'error': str(e)}), 500


# # ======================== 4. SEND IMAGE TO ADMIN (From Gallery) ========================
# @app.route('/api/send_drone_image', methods=['POST', 'OPTIONS'])
# def send_drone_image():
#     """Send image from gallery to admin (manual, one-off — unrelated to operations)"""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     try:
#         print("=" * 50)
#         print("📸 Image received from Gallery to Admin")

#         data = request.get_json()
#         if not data:
#             print("❌ No JSON data received")
#             return jsonify({'error': 'No data provided'}), 400

#         user_id = data.get('userId', 'unknown')
#         username = data.get('username', 'Unknown')
#         user_email = data.get('userEmail', '')
#         is_admin = data.get('isAdmin', False)
#         timestamp = data.get('timestamp', datetime.datetime.now().isoformat())

#         print(f"  👤 User: {username}")
#         print(f"  📧 Email: {user_email}")
#         print(f"  👑 Admin: {is_admin}")
#         print(f"  📁 Filename: {data.get('filename', 'Unknown')}")

#         image_base64 = data.get('image', '')
#         if not image_base64:
#             return jsonify({'error': 'No image data provided'}), 400

#         try:
#             image_bytes = base64.b64decode(image_base64)
#             print(f"✅ Image decoded: {len(image_bytes)} bytes")
#         except Exception as e:
#             print(f"❌ Invalid base64 image data: {str(e)}")
#             return jsonify({'error': f'Invalid base64 image data: {str(e)}'}), 400

#         timestamp_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
#         original_filename = data.get('filename', 'image.jpg')
#         extension = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'jpg'
#         filename = f"from_gallery_{timestamp_str}.{extension}"
#         filepath = os.path.join(UPLOAD_FOLDER, filename)

#         with open(filepath, 'wb') as f:
#             f.write(image_bytes)
#         print(f"✅ Image saved: {filepath}")

#         metadata = data.get('metadata', {})
#         metadata.update({
#             'imageName': filename,
#             'uploadedAt': datetime.datetime.now().isoformat(),
#             'userId': user_id,
#             'username': username,
#             'userEmail': user_email,
#             'isAdmin': is_admin,
#             'source': 'gallery_to_admin',
#             'status': 'received_from_gallery',
#             'timestamp': timestamp,
#         })

#         base_name = filename.rsplit('.', 1)[0]
#         metadata_path = os.path.join(METADATA_FOLDER, f"{base_name}.json")
#         with open(metadata_path, 'w') as f:
#             json.dump(metadata, f, indent=2)
#         print(f"✅ Metadata saved with username: {username}")

#         received_image_entry = {
#             'id': datetime.datetime.now().timestamp(),
#             'filename': filename,
#             'metadata': metadata,
#             'image': image_base64,
#             'receivedAt': datetime.datetime.now().isoformat(),
#             'userId': user_id,
#             'username': username,
#             'userEmail': user_email,
#             'isAdmin': is_admin,
#         }

#         with received_images_lock:
#             received_images.insert(0, received_image_entry)
#             if len(received_images) > MAX_RECEIVED_IMAGES:
#                 del received_images[MAX_RECEIVED_IMAGES:]

#         threading.Thread(target=save_received_images_to_file).start()

#         return jsonify({
#             'success': True,
#             'message': f'Image from {username} sent to admin successfully',
#             'filename': filename,
#             'username': username,
#             'total_images': len(received_images)
#         }), 200

#     except Exception as e:
#         print(f"❌ Send image error: {str(e)}")
#         import traceback
#         traceback.print_exc()
#         return jsonify({'error': str(e)}), 500


# # ======================== 5. GET RECEIVED IMAGES (Admin Dashboard) ========================

# @app.route('/api/get_received_images', methods=['GET', 'OPTIONS'])
# def get_received_images():
#     """Get all images sent from gallery to admin"""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     try:
#         if not received_images:
#             load_received_images_from_file()

#         with received_images_lock:
#             images_to_return = []
#             for img in received_images[:100]:
#                 img_copy = img.copy()
#                 if 'metadata' in img_copy and img_copy['metadata']:
#                     img_copy['username'] = img_copy['metadata'].get('username', 'Unknown')
#                 else:
#                     img_copy['username'] = img_copy.get('username', 'Unknown')
#                 images_to_return.append(img_copy)

#         return jsonify({
#             'success': True,
#             'count': len(images_to_return),
#             'total': len(received_images),
#             'images': images_to_return,
#             'timestamp': datetime.datetime.now().isoformat()
#         }), 200

#     except Exception as e:
#         print(f"❌ Get received images error: {str(e)}")
#         return jsonify({'error': str(e)}), 500


# # ======================== 6. GET LIVE DATA (Legacy Admin Dashboard) ========================

# @app.route('/api/live_data', methods=['GET'])
# def get_live_data():
#     """Get all legacy live data for admin dashboard"""
#     try:
#         with live_data_lock:
#             history = list(live_data_store)[-50:] if live_data_store else []
#             data = {
#                 'success': True,
#                 'total_points': len(live_data_store),
#                 'latest_position': latest_drone_position,
#                 'history': history,
#                 'timestamp': datetime.datetime.now().isoformat()
#             }
#         return jsonify(data), 200
#     except Exception as e:
#         print(f"❌ Get live data error: {str(e)}")
#         return jsonify({'error': str(e)}), 500


# # ======================== 7. GET ALL IMAGES ========================

# @app.route('/api/images', methods=['GET'])
# def get_images():
#     """Get list of uploaded images with metadata (flat uploads folder only)"""
#     try:
#         images = []
#         if not os.path.exists(UPLOAD_FOLDER):
#             return jsonify({'success': True, 'count': 0, 'images': images}), 200

#         for filename in os.listdir(UPLOAD_FOLDER):
#             full_path = os.path.join(UPLOAD_FOLDER, filename)
#             if os.path.isdir(full_path):
#                 continue  # skip operation photo subfolders — use /api/live_operations for those
#             if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
#                 base_name = filename.rsplit('.', 1)[0]
#                 metadata_path = os.path.join(METADATA_FOLDER, f"{base_name}.json")
#                 metadata = None
#                 if os.path.exists(metadata_path):
#                     try:
#                         with open(metadata_path, 'r') as f:
#                             metadata = json.load(f)
#                     except Exception:
#                         metadata = None

#                 images.append({
#                     'filename': filename,
#                     'url': f'/uploads/{filename}',
#                     'metadata': metadata
#                 })

#         return jsonify({'success': True, 'count': len(images), 'images': images}), 200

#     except Exception as e:
#         print(f"❌ Get images error: {str(e)}")
#         return jsonify({'error': str(e)}), 500


# # ======================== 8. SERVE UPLOADED IMAGE ========================
# # Widened to <path:filepath> so it also serves operation photos, which live
# # under a subfolder: /uploads/<operationId>/wp_<n>.jpg

# @app.route('/uploads/<path:filepath>', methods=['GET'])
# def get_uploaded_image(filepath):
#     """Serve an uploaded image, flat or nested under an operation folder."""
#     try:
#         full_path = os.path.join(UPLOAD_FOLDER, filepath)
#         # Prevent path traversal outside the uploads folder.
#         if not os.path.abspath(full_path).startswith(os.path.abspath(UPLOAD_FOLDER)):
#             return jsonify({'error': 'Invalid path'}), 400
#         if not os.path.exists(full_path):
#             return jsonify({'error': 'Image not found'}), 404
#         return send_file(full_path, mimetype='image/jpeg')
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500


# # ======================== 9. DELETE IMAGE ========================

# @app.route('/api/delete/<filename>', methods=['DELETE'])
# def delete_image(filename):
#     """Delete a flat (non-operation) image and its metadata"""
#     try:
#         filepath = os.path.join(UPLOAD_FOLDER, filename)
#         if os.path.exists(filepath) and os.path.isfile(filepath):
#             os.remove(filepath)
#             print(f"✅ Deleted image: {filepath}")

#         base_name = filename.rsplit('.', 1)[0]
#         metadata_path = os.path.join(METADATA_FOLDER, f"{base_name}.json")
#         if os.path.exists(metadata_path):
#             os.remove(metadata_path)
#             print(f"✅ Deleted metadata: {metadata_path}")

#         with received_images_lock:
#             global received_images
#             received_images = [img for img in received_images if img.get('filename') != filename]

#         return jsonify({'success': True, 'message': f'Deleted {filename} and its metadata'}), 200

#     except Exception as e:
#         print(f"❌ Delete error: {str(e)}")
#         return jsonify({'error': str(e)}), 500


# # ======================== 10. CLEAR LIVE DATA (legacy) ========================

# @app.route('/api/live_data/clear', methods=['POST'])
# def clear_live_data():
#     """Clear all legacy live data"""
#     try:
#         with live_data_lock:
#             live_data_store.clear()
#             latest_drone_position.update({
#                 'latitude': None, 'longitude': None, 'altitude': None,
#                 'distance': None, 'compass': None, 'timestamp': None,
#                 'droneType': None, 'status': 'idle'
#             })
#         save_live_data_to_file()
#         return jsonify({'success': True, 'message': 'Live data cleared'}), 200
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500


# # ======================== 11. CLEAR RECEIVED IMAGES ========================

# @app.route('/api/received_images/clear', methods=['POST'])
# def clear_received_images():
#     """Clear all received images"""
#     try:
#         with received_images_lock:
#             received_images.clear()
#         save_received_images_to_file()
#         return jsonify({'success': True, 'message': 'Received images cleared'}), 200
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500


# # ======================== 12. LIVE OPERATIONS (pure REST — no sockets) ========================
# #
# # Every one of these is a plain HTTP request/response. There is no
# # WebSocket, no SSE, no push channel. The admin side only ever sees new
# # data when it explicitly calls GET (e.g. the person taps a refresh
# # button / pulls to refresh) — nothing here pushes to the client.

# @app.route('/api/live_operations/start', methods=['POST', 'OPTIONS'])
# def start_live_operation():
#     """Called when the user taps LIVE on Drone Ranger. Creates one operation
#     with its own id + assigned color; every subsequent point/photo until
#     Stop is tapped belongs to this operation."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     data = request.get_json() or {}
#     username = data.get('username', 'Unknown')

#     with operations_lock:
#         op_index = count_user_operations(username)
#         color = assign_operation_color(username, op_index)
#         operation_id = f"{secure_filename(username)}_{int(time.time() * 1000)}"

#         operation = {
#             'operationId': operation_id,
#             'userId': data.get('userId', 'unknown'),
#             'username': username,
#             'userEmail': data.get('userEmail', ''),
#             'isAdmin': data.get('isAdmin', False),
#             'droneCategory': data.get('droneCategory', 'Custom'),
#             'activeMode': data.get('activeMode', 'unknown'),
#             'activeModeName': data.get('activeModeName', 'Unknown'),
#             'color': color,
#             'operationIndexForUser': op_index,
#             'startTime': datetime.datetime.now().isoformat(),
#             'endTime': None,
#             'status': 'active',
#             'points': [],
#         }
#         active_operations[operation_id] = operation
#         save_operation(operation)

#     print(f"🟢 Operation started: {operation_id} ({username}, color {color})")
#     return jsonify({'success': True, 'operationId': operation_id, 'color': color}), 201


# @app.route('/api/live_operations/<operation_id>/point', methods=['POST', 'OPTIONS'])
# def add_operation_point(operation_id):
#     """Adds one telemetry point to an active operation. Called every ~2s
#     while streaming (or once for a manual single send)."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     data = request.get_json() or {}

#     with operations_lock:
#         op = get_operation(operation_id)
#         if op is None:
#             return jsonify({'error': 'operation not found'}), 404
#         if op['status'] != 'active':
#             return jsonify({'error': 'operation is not active'}), 409

#         waypoint_number = len(op['points']) + 1
#         point = {
#             'waypointNumber': waypoint_number,
#             'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
#             'pitch': float(data.get('pitch', 0)),
#             'roll': float(data.get('roll', 0)),
#             'compass': float(data.get('compass', 0)),
#             'distance': float(data.get('distance', 0)),
#             'altitude': float(data.get('altitude', 0)),
#             'drone_latitude': data.get('drone_latitude', 'N/A'),
#             'drone_longitude': data.get('drone_longitude', 'N/A'),
#             'user_latitude': data.get('user_latitude', 'N/A'),
#             'user_longitude': data.get('user_longitude', 'N/A'),
#             'zoomLevel': float(data.get('zoomLevel', 1.0)),
#             'boxSize': float(data.get('boxSize', 0)),
#             'imageUrl': None,
#         }
#         op['points'].append(point)
#         save_operation(op)

#     return jsonify({'success': True, 'waypointNumber': waypoint_number}), 200


# @app.route('/api/live_operations/<operation_id>/photo', methods=['POST', 'OPTIONS'])
# def add_operation_photo(operation_id):
#     """Attaches a photo to a specific waypoint of an operation. The Flutter
#     side sends the SAME waypointNumber it got back from /point for that
#     tick, so the point and its photo line up."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     data = request.get_json() or {}
#     waypoint_number = int(data.get('waypointNumber', 0))
#     image_b64 = data.get('image', '')
#     if not image_b64:
#         return jsonify({'error': 'no image data'}), 400

#     try:
#         image_bytes = base64.b64decode(image_b64)
#     except Exception as e:
#         return jsonify({'error': f'invalid base64: {e}'}), 400

#     op_dir = os.path.join(UPLOAD_FOLDER, secure_filename(operation_id))
#     os.makedirs(op_dir, exist_ok=True)
#     filename = f'wp_{waypoint_number}.jpg'
#     with open(os.path.join(op_dir, filename), 'wb') as f:
#         f.write(image_bytes)

#     image_url = f'/uploads/{operation_id}/{filename}'

#     with operations_lock:
#         op = get_operation(operation_id)
#         if op:
#             for p in op['points']:
#                 if p['waypointNumber'] == waypoint_number:
#                     p['imageUrl'] = image_url
#                     break
#             save_operation(op)

#     return jsonify({'success': True, 'imageUrl': image_url}), 200


# @app.route('/api/live_operations/<operation_id>/stop', methods=['POST', 'OPTIONS'])
# def stop_live_operation(operation_id):
#     """Called when the user taps STOP. Finalizes the operation file."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     with operations_lock:
#         op = get_operation(operation_id)
#         if op is None:
#             return jsonify({'error': 'operation not found'}), 404
#         op['endTime'] = datetime.datetime.now().isoformat()
#         op['status'] = 'completed'
#         save_operation(op)
#         active_operations.pop(operation_id, None)

#     print(f"🔴 Operation stopped: {operation_id} ({len(op['points'])} points)")
#     return jsonify({'success': True, 'operation': op}), 200


# @app.route('/api/live_operations', methods=['GET'])
# def list_live_operations():
#     """Lightweight list for the operations picker — no point arrays, so it
#     stays fast even with thousands of saved operations. Supports optional
#     ?status=active and ?username=<name> filters."""
#     status_filter = request.args.get('status')
#     username_filter = request.args.get('username')

#     operations = []
#     if os.path.exists(OPERATIONS_FOLDER):
#         for fname in sorted(os.listdir(OPERATIONS_FOLDER), reverse=True):
#             if not fname.endswith('.json'):
#                 continue
#             try:
#                 with open(os.path.join(OPERATIONS_FOLDER, fname)) as f:
#                     d = json.load(f)
#             except Exception:
#                 continue

#             if status_filter and d.get('status') != status_filter:
#                 continue
#             if username_filter and d.get('username') != username_filter:
#                 continue

#             operations.append({
#                 'operationId': d['operationId'],
#                 'username': d['username'],
#                 'userId': d.get('userId'),
#                 'color': d.get('color'),
#                 'startTime': d.get('startTime'),
#                 'endTime': d.get('endTime'),
#                 'status': d.get('status'),
#                 'pointCount': len(d.get('points', [])),
#                 'droneCategory': d.get('droneCategory'),
#                 'activeModeName': d.get('activeModeName'),
#             })

#     return jsonify({'success': True, 'count': len(operations), 'operations': operations}), 200


# @app.route('/api/live_operations/<operation_id>', methods=['GET'])
# def get_live_operation_detail(operation_id):
#     """Full operation detail including all points (each with its imageUrl),
#     for the table/map pages."""
#     op = get_operation(operation_id)
#     if op is None:
#         return jsonify({'error': 'operation not found'}), 404
#     return jsonify({'success': True, 'operation': op}), 200


# @app.route('/api/live_operations/<operation_id>', methods=['DELETE', 'OPTIONS'])
# def delete_live_operation(operation_id):
#     """Deletes an operation's record file and its whole photo folder."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     with operations_lock:
#         op = get_operation(operation_id)
#         active_operations.pop(operation_id, None)

#     deleted_file = False
#     path = operation_file_path(operation_id)
#     if os.path.exists(path):
#         try:
#             os.remove(path)
#             deleted_file = True
#         except Exception as e:
#             print(f"❌ Error deleting operation file {operation_id}: {e}")

#     deleted_photos = 0
#     op_dir = os.path.join(UPLOAD_FOLDER, secure_filename(operation_id))
#     if os.path.isdir(op_dir):
#         try:
#             for fname in os.listdir(op_dir):
#                 fpath = os.path.join(op_dir, fname)
#                 if os.path.isfile(fpath):
#                     os.remove(fpath)
#                     deleted_photos += 1
#             os.rmdir(op_dir)
#         except Exception as e:
#             print(f"❌ Error deleting operation photos {operation_id}: {e}")

#     if op is None and not deleted_file and deleted_photos == 0:
#         return jsonify({'error': 'operation not found'}), 404

#     print(f"🗑️ Deleted operation: {operation_id} ({deleted_photos} photos)")
#     return jsonify({'success': True, 'operationId': operation_id, 'deletedPhotos': deleted_photos}), 200


# @app.route('/api/live_operations/clear', methods=['POST', 'OPTIONS'])
# def clear_live_operations():
#     """Deletes ALL saved operations and their photos. For admin/testing
#     cleanup — added for parity with /api/live_data/clear and
#     /api/received_images/clear. Not wired to any button in the app yet."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     deleted = 0
#     with operations_lock:
#         active_operations.clear()
#         if os.path.exists(OPERATIONS_FOLDER):
#             for fname in os.listdir(OPERATIONS_FOLDER):
#                 if fname.endswith('.json'):
#                     try:
#                         os.remove(os.path.join(OPERATIONS_FOLDER, fname))
#                         deleted += 1
#                     except Exception as e:
#                         print(f"❌ Error deleting {fname}: {e}")

#     if os.path.exists(UPLOAD_FOLDER):
#         for name in os.listdir(UPLOAD_FOLDER):
#             full = os.path.join(UPLOAD_FOLDER, name)
#             if os.path.isdir(full):
#                 try:
#                     for fname in os.listdir(full):
#                         os.remove(os.path.join(full, fname))
#                     os.rmdir(full)
#                 except Exception as e:
#                     print(f"❌ Error clearing operation folder {name}: {e}")

#     return jsonify({'success': True, 'deletedOperations': deleted}), 200


# # ======================== 13. HEALTH CHECK ========================

# @app.route('/health', methods=['GET'])
# def health_check():
#     op_count = 0
#     if os.path.exists(OPERATIONS_FOLDER):
#         op_count = len([f for f in os.listdir(OPERATIONS_FOLDER) if f.endswith('.json')])
#     return jsonify({
#         'status': 'ok',
#         'timestamp': datetime.datetime.now().isoformat(),
#         'upload_folder': UPLOAD_FOLDER,
#         'metadata_folder': METADATA_FOLDER,
#         'operations_folder': OPERATIONS_FOLDER,
#         'live_data_points': len(live_data_store),
#         'received_images': len(received_images),
#         'active_operations': len(active_operations),
#         'total_operations': op_count,
#         'upload_folder_exists': os.path.exists(UPLOAD_FOLDER),
#         'metadata_folder_exists': os.path.exists(METADATA_FOLDER),
#         'database_configured': bool(DATABASE_URL),
#     }), 200


# # ======================== 14. AUTH (POSTGRES + OTP LOGIN) ========================

# @app.route('/api/auth/request-otp', methods=['POST', 'OPTIONS'])
# def request_otp():
#     """Person enters their email → we confirm the account exists and
#     (for now) just print the fixed OTP to the server logs instead of
#     actually sending it anywhere."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     data = request.get_json() or {}
#     email = (data.get('email') or '').strip().lower()
#     if not email:
#         return jsonify({'success': False, 'message': 'Email is required'}), 400

#     try:
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute('SELECT id FROM users WHERE email = %s', (email,))
#         user = cur.fetchone()
#         cur.close()
#         conn.close()
#     except Exception as e:
#         return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

#     if user is None:
#         return jsonify({'success': False, 'message': 'No account found with this email'}), 404

#     print(f'📩 [TEMP OTP] Code for {email}: {TEMP_OTP}')
#     return jsonify({'success': True, 'message': f'OTP sent to {email}'}), 200


# @app.route('/api/auth/verify-otp', methods=['POST', 'OPTIONS'])
# def verify_otp():
#     """Person enters the OTP → checked against the fixed TEMP_OTP value.
#     On success, returns the user's profile (email, displayName, role).

#     Device lock: the client sends a deviceId (a random ID generated once
#     on first app launch, persisted locally — NOT a network IP, since
#     those change constantly). The FIRST successful login for an account
#     binds it to that deviceId. Every login after that must send the same
#     deviceId, or it's rejected — so a stolen/shared email+OTP can't be
#     used to log the same account in from a different phone."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     data = request.get_json() or {}
#     email = (data.get('email') or '').strip().lower()
#     otp = (data.get('otp') or '').strip()
#     device_id = (data.get('deviceId') or '').strip()

#     if not email or not otp:
#         return jsonify({'success': False, 'message': 'Email and OTP are required'}), 400
#     if not device_id:
#         return jsonify({'success': False, 'message': 'Missing device ID'}), 400

#     if otp != TEMP_OTP:
#         return jsonify({'success': False, 'message': 'Invalid OTP'}), 401

#     try:
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute('SELECT * FROM users WHERE email = %s', (email,))
#         user = cur.fetchone()
#         if user is None:
#             cur.close()
#             conn.close()
#             return jsonify({'success': False, 'message': 'No account found with this email'}), 404

#         existing_device = user['device_id']

#         if existing_device is None:
#             # First login ever for this account — bind it to this device.
#             cur.execute(
#                 'UPDATE users SET device_id = %s, last_login = NOW() WHERE email = %s',
#                 (device_id, email)
#             )
#             conn.commit()
#         elif existing_device != device_id:
#             # Bound to a DIFFERENT device already — reject.
#             cur.close()
#             conn.close()
#             return jsonify({
#                 'success': False,
#                 'message': 'This account is already signed in on another device. Contact an admin to reset it.'
#             }), 403
#         else:
#             # Same device as before — normal login.
#             cur.execute('UPDATE users SET last_login = NOW() WHERE email = %s', (email,))
#             conn.commit()

#         cur.close()
#         conn.close()
#     except Exception as e:
#         return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

#     return jsonify({
#         'success': True,
#         'message': 'Login successful',
#         'user': {
#             'id': user['id'],
#             'email': user['email'],
#             'displayName': user['display_name'],
#             'role': user['role'],
#         }
#     }), 200


# @app.route('/api/auth/users', methods=['GET'])
# def list_users():
#     """List all accounts — admin/debug use. device_id shows which phone
#     (if any) each account is currently locked to."""
#     try:
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute('SELECT id, email, display_name, role, device_id, created_at, last_login FROM users ORDER BY id')
#         users = cur.fetchall()
#         cur.close()
#         conn.close()
#         return jsonify({'success': True, 'count': len(users), 'users': users}), 200
#     except Exception as e:
#         return jsonify({'success': False, 'message': str(e)}), 500


# @app.route('/api/auth/users/reset-device', methods=['POST', 'OPTIONS'])
# def reset_user_device():
#     """Clears the device lock for one account (e.g. they got a new phone,
#     or you're testing). The next OTP login from ANY device will re-bind.
#     Admin/debug use — lock this down once you have real admin auth."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     data = request.get_json() or {}
#     email = (data.get('email') or '').strip().lower()
#     if not email:
#         return jsonify({'success': False, 'message': 'Email is required'}), 400

#     try:
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute(
#             'UPDATE users SET device_id = NULL WHERE email = %s RETURNING id',
#             (email,)
#         )
#         row = cur.fetchone()
#         conn.commit()
#         cur.close()
#         conn.close()
#     except Exception as e:
#         return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

#     if row is None:
#         return jsonify({'success': False, 'message': 'No account found with this email'}), 404

#     return jsonify({'success': True, 'message': f'Device lock cleared for {email}'}), 200


# @app.route('/api/auth/users', methods=['POST', 'OPTIONS'])
# def create_user():
#     """Add a new account — admin/debug use while login data is static.
#     Lock this down (or remove it) once you have real admin auth in front
#     of it."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     data = request.get_json() or {}
#     email = (data.get('email') or '').strip().lower()
#     display_name = (data.get('displayName') or email.split('@')[0]).strip()
#     role = (data.get('role') or 'user').strip()

#     if not email:
#         return jsonify({'success': False, 'message': 'Email is required'}), 400

#     try:
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute(
#             'INSERT INTO users (email, display_name, role) VALUES (%s, %s, %s) '
#             'ON CONFLICT (email) DO NOTHING RETURNING id',
#             (email, display_name, role)
#         )
#         row = cur.fetchone()
#         conn.commit()
#         cur.close()
#         conn.close()
#     except Exception as e:
#         return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

#     if row is None:
#         return jsonify({'success': False, 'message': 'That email is already registered'}), 409

#     return jsonify({'success': True, 'message': 'User created', 'id': row['id']}), 201


# # ======================== 15. INDEX / API INFO ========================

# @app.route('/', methods=['GET'])
# def index():
#     return jsonify({
#         'name': 'Drone Ranger API',
#         'version': '3.1.0',
#         'endpoints': [
#             {'path': '/', 'method': 'GET', 'description': 'API info'},
#             {'path': '/health', 'method': 'GET', 'description': 'Health check'},
#             {'path': '/api/upload_drone_image', 'method': 'POST', 'description': 'Upload image with metadata'},
#             {'path': '/api/send_drone_data', 'method': 'POST', 'description': 'Legacy: send one-off drone data'},
#             {'path': '/api/send_live_data', 'method': 'POST', 'description': 'Legacy fallback: single live data send'},
#             {'path': '/api/send_drone_image', 'method': 'POST', 'description': 'Send image from gallery to admin'},
#             {'path': '/api/get_received_images', 'method': 'GET', 'description': 'Get images sent to admin'},
#             {'path': '/api/live_data', 'method': 'GET', 'description': 'Legacy: get flat live data (poll on demand, no push)'},
#             {'path': '/api/live_data/clear', 'method': 'POST', 'description': 'Legacy: clear live data'},
#             {'path': '/api/received_images/clear', 'method': 'POST', 'description': 'Clear received images'},
#             {'path': '/api/images', 'method': 'GET', 'description': 'Get all flat images'},
#             {'path': '/uploads/<path:filepath>', 'method': 'GET', 'description': 'Get uploaded image (flat or per-operation)'},
#             {'path': '/api/delete/<filename>', 'method': 'DELETE', 'description': 'Delete a flat image'},
#             {'path': '/api/live_operations/start', 'method': 'POST', 'description': 'Start a new live operation (tap LIVE)'},
#             {'path': '/api/live_operations/<id>/point', 'method': 'POST', 'description': 'Add a telemetry point to an operation'},
#             {'path': '/api/live_operations/<id>/photo', 'method': 'POST', 'description': 'Attach a photo to a waypoint'},
#             {'path': '/api/live_operations/<id>/stop', 'method': 'POST', 'description': 'Stop and finalize an operation (tap STOP)'},
#             {'path': '/api/live_operations', 'method': 'GET', 'description': 'List all operations (summary)'},
#             {'path': '/api/live_operations/<id>', 'method': 'GET', 'description': 'Get full operation detail + points'},
#             {'path': '/api/live_operations/<id>', 'method': 'DELETE', 'description': 'Delete an operation + its photos'},
#             {'path': '/api/live_operations/clear', 'method': 'POST', 'description': 'Delete ALL operations + photos'},
#             {'path': '/api/auth/request-otp', 'method': 'POST', 'description': 'Step 1: request OTP for an email (Postgres-backed)'},
#             {'path': '/api/auth/verify-otp', 'method': 'POST', 'description': 'Step 2: verify OTP and log in'},
#             {'path': '/api/auth/users', 'method': 'GET', 'description': 'List all user accounts (includes device lock status)'},
#             {'path': '/api/auth/users', 'method': 'POST', 'description': 'Create a new user account'},
#             {'path': '/api/auth/users/reset-device', 'method': 'POST', 'description': 'Clear a device lock (e.g. user got a new phone)'},
#         ]
#     }), 200


# # ======================== LOAD DATA ON STARTUP ========================
# load_live_data_from_file()
# load_received_images_from_file()
# init_auth_db()

# # Start the background sweeper that auto-closes stale "active" operations
# # (e.g. app crashed mid-stream without hitting Stop).
# threading.Thread(target=stale_active_operation_sweeper, daemon=True).start()

# print("=" * 50)
# print("🚀 Drone Ranger API Server Started")
# print(f"📁 Upload folder: {UPLOAD_FOLDER}")
# print(f"📁 Metadata folder: {METADATA_FOLDER}")
# print(f"📁 Operations folder: {OPERATIONS_FOLDER}")
# print(f"📊 Live data points: {len(live_data_store)}")
# print(f"🖼️ Received images: {len(received_images)}")
# print(f"🔐 Database configured: {bool(DATABASE_URL)}")
# print("=" * 50)

# # ======================== FOR RENDER / PYTHONANYWHERE ========================
# # DO NOT use app.run() on Render or PythonAnywhere — both use a WSGI
# # server (gunicorn on Render) that imports `app` directly from this file.

# # If you want to test locally, uncomment the line below:
# # if __name__ == '__main__':
# #     app.run(debug=True, host='0.0.0.0', port=5001)
import os
import json
import datetime
import hashlib
import colorsys
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import time
import threading
import sys
from collections import deque
import base64
import psycopg2
import psycopg2.extras

app = Flask(__name__)
CORS(app, origins='*')

# ======================== CONFIGURATION ========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
METADATA_FOLDER = os.path.join(BASE_DIR, 'metadata')
OPERATIONS_FOLDER = os.path.join(BASE_DIR, 'operations')
LIVE_DATA_FILE = os.path.join(BASE_DIR, 'live_data.json')
RECEIVED_IMAGES_FILE = os.path.join(BASE_DIR, 'received_images.json')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Create folders if they don't exist
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(METADATA_FOLDER, exist_ok=True)
    os.makedirs(OPERATIONS_FOLDER, exist_ok=True)
    print(f"✅ Upload folder: {UPLOAD_FOLDER}")
    print(f"✅ Metadata folder: {METADATA_FOLDER}")
    print(f"✅ Operations folder: {OPERATIONS_FOLDER}")
except Exception as e:
    print(f"❌ Error creating folders: {e}")

# ======================== AUTH / POSTGRES CONFIGURATION ========================
DATABASE_URL = os.environ.get('DATABASE_URL', '')
# Render (and some other hosts) hand out "postgres://..." but psycopg2's
# newer versions want "postgresql://..." — normalize it either way.
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# TEMPORARY: fixed OTP for every login attempt. Replace this with a real
# SMS/email OTP provider (Twilio, SES, etc.) later — search for TEMP_OTP
# in this file when you're ready to wire that in.
TEMP_OTP = '1234'

# "login data will static" — same 4 accounts from the old Flutter
# AuthService, now seeded into Postgres once on first startup.
STATIC_USERS = [
    {'email': 'superadmin@system.com', 'password': 'securepass', 'displayName': 'System Admin', 'role': 'superadmin'},
    {'email': 'company@company.com', 'password': 'securepass', 'displayName': 'Company Admin', 'role': 'companyadmin'},
    {'email': 'controller@drone.com', 'password': 'securepass', 'displayName': 'Drone Controller', 'role': 'controller'},
    {'email': 'user@drone.com', 'password': 'securepass', 'displayName': 'Regular User', 'role': 'user'},
]

# ======================== LIVE DATA STORAGE (LEGACY) ========================
# Kept for backward compatibility / the old single-point endpoints.
# New work should use the Operations system below.
MAX_LIVE_DATA_POINTS = 1000
live_data_store = deque(maxlen=MAX_LIVE_DATA_POINTS)
live_data_lock = threading.Lock()

latest_drone_position = {
    'latitude': None,
    'longitude': None,
    'altitude': None,
    'distance': None,
    'compass': None,
    'timestamp': None,
    'droneType': None,
    'status': 'idle'
}

# ======================== RECEIVED IMAGES STORAGE (LEGACY) ========================
received_images = []
received_images_lock = threading.Lock()
MAX_RECEIVED_IMAGES = 500

# ======================== LIVE OPERATIONS STORAGE ========================
#
# An "operation" is one Live -> Stop session on the app. Each operation:
#   - gets a unique operationId and an assigned color (stable per-user hue,
#     shifted lightness per session so the same user's Nth session looks
#     different from their 1st)
#   - is persisted as its own JSON file under /operations/<operationId>.json
#   - has its captured photos saved under /uploads/<operationId>/wp_<n>.jpg,
#     with each point's `imageUrl` pointing at its own photo
#
# active_operations mirrors in-memory state for operations currently being
# written to; completed/older operations are read straight from disk.

operations_lock = threading.Lock()
active_operations = {}  # operation_id -> dict

# Distinct lightness steps so the SAME user's different sessions are
# visibly different shades of their own hue, not randomly re-picked colors.
_LIGHTNESS_STEPS = [55, 38, 70, 30, 82, 46, 64, 25]


def _cors_ok():
    r = jsonify({'status': 'ok'})
    r.headers.add('Access-Control-Allow-Origin', '*')
    r.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, DELETE')
    r.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    return r


def operation_file_path(op_id):
    return os.path.join(OPERATIONS_FOLDER, f'{secure_filename(op_id)}.json')


def save_operation(op):
    try:
        with open(operation_file_path(op['operationId']), 'w') as f:
            json.dump(op, f, indent=2)
    except Exception as e:
        print(f"❌ Error saving operation {op.get('operationId')}: {e}")


def load_operation_from_disk(op_id):
    path = operation_file_path(op_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error loading operation {op_id}: {e}")
        return None


def get_operation(op_id):
    """Get from memory, falling back to disk (covers server restarts)."""
    op = active_operations.get(op_id)
    if op is None:
        op = load_operation_from_disk(op_id)
        if op is not None:
            active_operations[op_id] = op
    return op


def count_user_operations(username):
    count = 0
    if not os.path.exists(OPERATIONS_FOLDER):
        return 0
    for fname in os.listdir(OPERATIONS_FOLDER):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(OPERATIONS_FOLDER, fname)) as f:
                if json.load(f).get('username') == username:
                    count += 1
        except Exception:
            pass
    return count


def assign_operation_color(username, op_index_for_user):
    """Stable hue per username (so a user is always roughly the same
    color family), distinct lightness per operation index (so session #1
    vs session #2 for the same user are visibly different shades)."""
    hue = int(hashlib.md5(username.encode()).hexdigest(), 16) % 360
    lightness = _LIGHTNESS_STEPS[op_index_for_user % len(_LIGHTNESS_STEPS)]
    r, g, b = colorsys.hls_to_rgb(hue / 360, lightness / 100, 0.65)
    return '#{:02X}{:02X}{:02X}'.format(int(r * 255), int(g * 255), int(b * 255))


def stale_active_operation_sweeper():
    """Background thread: auto-closes operations that have gone silent
    for too long (e.g. app crashed mid-stream without hitting Stop),
    so they don't sit as 'active' forever."""
    STALE_AFTER_SECONDS = 180  # 3 minutes with no new point
    while True:
        time.sleep(60)
        try:
            now = datetime.datetime.now()
            with operations_lock:
                stale_ids = []
                for op_id, op in list(active_operations.items()):
                    if op.get('status') != 'active':
                        continue
                    last_ts_str = None
                    if op.get('points'):
                        last_ts_str = op['points'][-1].get('timestamp')
                    else:
                        last_ts_str = op.get('startTime')
                    if not last_ts_str:
                        continue
                    try:
                        last_ts = datetime.datetime.fromisoformat(last_ts_str)
                    except Exception:
                        continue
                    if (now - last_ts).total_seconds() > STALE_AFTER_SECONDS:
                        stale_ids.append(op_id)

                for op_id in stale_ids:
                    op = active_operations[op_id]
                    op['status'] = 'completed'
                    op['endTime'] = now.isoformat()
                    op['autoClosedReason'] = 'stale_no_activity'
                    save_operation(op)
                    active_operations.pop(op_id, None)
                    print(f"⚠️ Auto-closed stale operation: {op_id}")
        except Exception as e:
            print(f"❌ Stale sweeper error: {e}")


# ======================== HELPERS ========================
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_metadata(metadata, filename):
    """Save metadata as JSON file"""
    try:
        base_name = filename.rsplit('.', 1)[0]
        metadata_path = os.path.join(METADATA_FOLDER, f"{base_name}.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        return metadata_path
    except Exception as e:
        print(f"❌ Error saving metadata: {e}")
        return None


def save_live_data_to_file():
    """Save legacy live data to file for persistence"""
    try:
        with live_data_lock:
            data_to_save = {
                'timestamp': datetime.datetime.now().isoformat(),
                'latest_position': latest_drone_position,
                'history': list(live_data_store)
            }
        with open(LIVE_DATA_FILE, 'w') as f:
            json.dump(data_to_save, f, indent=2)
    except Exception as e:
        print(f"❌ Error saving live data: {e}")


def save_received_images_to_file():
    """Save received images to file for persistence"""
    try:
        with received_images_lock:
            data_to_save = {
                'timestamp': datetime.datetime.now().isoformat(),
                'images': received_images
            }
        with open(RECEIVED_IMAGES_FILE, 'w') as f:
            json.dump(data_to_save, f, indent=2)
    except Exception as e:
        print(f"❌ Error saving received images: {e}")


def load_live_data_from_file():
    """Load legacy live data from file on startup"""
    global latest_drone_position, live_data_store
    try:
        if os.path.exists(LIVE_DATA_FILE):
            with open(LIVE_DATA_FILE, 'r') as f:
                data = json.load(f)
                if 'latest_position' in data:
                    latest_drone_position = data['latest_position']
                if 'history' in data:
                    live_data_store.extend(data['history'])
            print(f"✅ Loaded {len(live_data_store)} live data points")
    except Exception as e:
        print(f"❌ Error loading live data: {e}")


def load_received_images_from_file():
    """Load received images from file on startup"""
    global received_images
    try:
        if os.path.exists(RECEIVED_IMAGES_FILE):
            with open(RECEIVED_IMAGES_FILE, 'r') as f:
                data = json.load(f)
                if 'images' in data:
                    received_images = data['images']
            print(f"✅ Loaded {len(received_images)} received images")
    except Exception as e:
        print(f"❌ Error loading received images: {e}")


# ======================== AUTH HELPERS (POSTGRES) ========================

def get_db():
    """One connection per request — fine at this traffic level with a
    single gunicorn worker. Swap for a connection pool later if needed."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_auth_db():
    """Creates the users table if missing and seeds the static accounts
    exactly once. Safe to call on every startup."""
    if not DATABASE_URL:
        print('⚠️ DATABASE_URL not set — /api/auth/* routes will fail until you add it on Render')
        return
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(255),
                display_name VARCHAR(255),
                role VARCHAR(50) NOT NULL DEFAULT 'user',
                created_at TIMESTAMP DEFAULT NOW(),
                last_login TIMESTAMP
            )
        ''')
        conn.commit()

        # Device-lock column. IF NOT EXISTS makes this safe to run against a
        # users table that already existed before this feature was added —
        # no separate manual migration step needed.
        cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS device_id VARCHAR(255)')
        conn.commit()

        cur.execute('SELECT COUNT(*) AS count FROM users')
        count = cur.fetchone()['count']
        if count == 0:
            for u in STATIC_USERS:
                cur.execute(
                    'INSERT INTO users (email, password, display_name, role) '
                    'VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING',
                    (u['email'], u['password'], u['displayName'], u['role'])
                )
            conn.commit()
            print(f'✅ Seeded {len(STATIC_USERS)} static users into Postgres')
        else:
            print(f'✅ Users table already has {count} row(s)')

        cur.close()
        conn.close()
    except Exception as e:
        print(f'❌ init_auth_db error: {e}')


# ======================== API ENDPOINTS ========================

# ======================== 1. UPLOAD IMAGE (From Drone Ranger) ========================

@app.route('/api/upload_drone_image', methods=['POST', 'OPTIONS'])
def upload_drone_image():
    """Upload image with metadata from Drone Ranger"""
    if request.method == 'OPTIONS':
        return _cors_ok()

    try:
        print("=" * 50)
        print("📸 Upload request received")
        print(f"Files: {request.files.keys()}")
        print(f"Form data: {request.form.keys()}")

        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400

        file = request.files['image']

        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400

        if file and allowed_file(file.filename):
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            original_filename = secure_filename(file.filename)
            extension = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'jpg'
            filename = f"drone_{timestamp}.{extension}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)

            file.save(filepath)
            print(f"✅ Image saved: {filepath}")

            user_id = request.form.get('userId', 'unknown')
            username = request.form.get('username', 'Unknown')
            user_email = request.form.get('userEmail', '')
            is_admin = request.form.get('isAdmin', 'false').lower() == 'true'

            metadata = {
                'pitch': request.form.get('pitch', '0.0'),
                'roll': request.form.get('roll', '0.0'),
                'compass': request.form.get('compass', '0.0'),
                'distance': request.form.get('distance', '0.0'),
                'latitude': request.form.get('latitude', 'N/A'),
                'longitude': request.form.get('longitude', 'N/A'),
                'timestamp': request.form.get('timestamp', datetime.datetime.now().isoformat()),
                'zoomLevel': request.form.get('zoomLevel', '1.0'),
                'boxSize': request.form.get('boxSize', '0'),
                'imageIndex': request.form.get('imageIndex', '0'),
                'imageName': filename,
                'uploadedAt': datetime.datetime.now().isoformat(),
                'status': 'received',
                'uploadedBy': username,
                'userId': user_id,
                'username': username,
                'userEmail': user_email,
                'isAdmin': is_admin,
                'source': 'drone_ranger'
            }

            save_metadata(metadata, filename)
            print(f"✅ Metadata saved for user: {username}")

            return jsonify({
                'success': True,
                'message': 'Image uploaded successfully',
                'filename': filename,
                'metadata': metadata
            }), 201

        else:
            return jsonify({'error': 'Invalid file type. Allowed: png, jpg, jpeg, gif'}), 400

    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ======================== 2. SEND DRONE DATA (Legacy — single photo_data send) ========================

@app.route('/api/send_drone_data', methods=['POST', 'OPTIONS'])
def send_drone_data():
    """Receive one-off drone data from mobile app (manual capture flow, not streaming)"""
    if request.method == 'OPTIONS':
        return _cors_ok()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        print("📡 Live data received:")
        print(f"  User: {data.get('username', 'Unknown')}")
        print(f"  Distance: {data.get('distance', 'N/A')}m")
        print(f"  Altitude: {data.get('altitude', 'N/A')}m")
        print(f"  Compass: {data.get('compass', 'N/A')}°")
        print(f"  Drone Size: {data.get('droneSize', 'N/A')}cm")

        user_id = data.get('userId', 'unknown')
        username = data.get('username', 'Unknown')
        user_email = data.get('userEmail', '')
        is_admin = data.get('isAdmin', False)

        live_data_point = {
            'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
            'pitch': float(data.get('pitch', 0)),
            'roll': float(data.get('roll', 0)),
            'compass': float(data.get('compass', 0)),
            'distance': float(data.get('distance', 0)),
            'horizontalDistance': float(data.get('horizontalDistance', 0)),
            'altitude': float(data.get('altitude', 0)),
            'latitude': data.get('latitude', 'N/A'),
            'longitude': data.get('longitude', 'N/A'),
            'zoomLevel': float(data.get('zoomLevel', 1.0)),
            'boxSize': float(data.get('boxSize', 0)),
            'droneSize': float(data.get('droneSize', 15.0)),
            'droneCategory': data.get('droneCategory', 'Custom'),
            'isCalibrated': data.get('isCalibrated', False),
            'calibrationPoints': int(data.get('calibrationPoints', 0)),
            'status': 'active',
            'userId': user_id,
            'username': username,
            'userEmail': user_email,
            'isAdmin': is_admin,
            'dataType': data.get('dataType', 'photo_data')
        }

        with live_data_lock:
            live_data_store.append(live_data_point)
            latest_drone_position.update({
                'latitude': data.get('latitude', 'N/A'),
                'longitude': data.get('longitude', 'N/A'),
                'altitude': data.get('altitude', 0),
                'distance': data.get('distance', 0),
                'compass': data.get('compass', 0),
                'droneSize': data.get('droneSize', 15.0),
                'droneCategory': data.get('droneCategory', 'Custom'),
                'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
                'status': 'active',
                'userId': user_id,
                'username': username
            })

        threading.Thread(target=save_live_data_to_file).start()

        return jsonify({
            'success': True,
            'message': 'Data received successfully',
            'data_received': True,
            'total_points': len(live_data_store)
        }), 200

    except Exception as e:
        print(f"❌ Send data error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ======================== 3. SEND LIVE DATA (Legacy fallback — used only when no operation is active) ========================

@app.route('/api/send_live_data', methods=['POST', 'OPTIONS'])
def send_live_data():
    """Legacy single live-data send to admin. The Flutter app now uses the
    Operations endpoints below for streaming; this route stays as a fallback
    for the manual 'Send Single Live Data' admin button when no Live
    operation is currently open."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        print("📡 Live data sent to Admin (legacy path):")
        print(f"  User: {data.get('username', 'Unknown')}")
        print(f"  Distance: {data.get('distance', 'N/A')}m")
        print(f"  Altitude: {data.get('altitude', 'N/A')}m")

        user_id = data.get('userId', 'unknown')
        username = data.get('username', 'Unknown')
        user_email = data.get('userEmail', '')
        is_admin = data.get('isAdmin', False)

        live_data_point = {
            'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
            'pitch': float(data.get('pitch', 0)),
            'roll': float(data.get('roll', 0)),
            'compass': float(data.get('compass', 0)),
            'distance': float(data.get('distance', 0)),
            'horizontalDistance': float(data.get('horizontalDistance', 0)),
            'altitude': float(data.get('altitude', 0)),
            'user_latitude': data.get('user_latitude', 'N/A'),
            'user_longitude': data.get('user_longitude', 'N/A'),
            'drone_latitude': data.get('drone_latitude', 'N/A'),
            'drone_longitude': data.get('drone_longitude', 'N/A'),
            'zoomLevel': float(data.get('zoomLevel', 1.0)),
            'boxSize': float(data.get('boxSize', 0)),
            'droneSize': float(data.get('droneSize', 15.0)),
            'droneCategory': data.get('droneCategory', 'Custom'),
            'activeMode': data.get('activeMode', 'Unknown'),
            'activeModeName': data.get('activeModeName', 'Unknown'),
            'activeModeIcon': data.get('activeModeIcon', '📐'),
            'isCalibrated': data.get('activeModeCalibrated', False),
            'calibrationPoints': int(data.get('activeModePoints', 0)),
            'userId': user_id,
            'username': username,
            'userEmail': user_email,
            'isAdmin': is_admin,
            'isContinuous': data.get('isContinuous', False),
            'sessionId': data.get('sessionId', ''),
            'sequenceNumber': data.get('sequenceNumber', 0),
            'hasDronePosition': data.get('hasDronePosition', False),
            'bearing': float(data.get('bearing', 0)),
            'dataType': 'live_data'
        }

        with live_data_lock:
            live_data_store.append(live_data_point)
            latest_drone_position.update({
                'latitude': data.get('drone_latitude', 'N/A'),
                'longitude': data.get('drone_longitude', 'N/A'),
                'altitude': data.get('altitude', 0),
                'distance': data.get('distance', 0),
                'compass': data.get('compass', 0),
                'droneSize': data.get('droneSize', 15.0),
                'droneCategory': data.get('droneCategory', 'Custom'),
                'activeMode': data.get('activeModeName', 'Unknown'),
                'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
                'status': 'active',
                'userId': user_id,
                'username': username,
                'userLat': data.get('user_latitude', 'N/A'),
                'userLng': data.get('user_longitude', 'N/A')
            })

        threading.Thread(target=save_live_data_to_file).start()

        return jsonify({
            'success': True,
            'message': 'Live data sent to admin',
            'total_points': len(live_data_store)
        }), 200

    except Exception as e:
        print(f"❌ Send live data error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ======================== 4. SEND IMAGE TO ADMIN (From Gallery) ========================
@app.route('/api/send_drone_image', methods=['POST', 'OPTIONS'])
def send_drone_image():
    """Send image from gallery to admin (manual, one-off — unrelated to operations)"""
    if request.method == 'OPTIONS':
        return _cors_ok()

    try:
        print("=" * 50)
        print("📸 Image received from Gallery to Admin")

        data = request.get_json()
        if not data:
            print("❌ No JSON data received")
            return jsonify({'error': 'No data provided'}), 400

        user_id = data.get('userId', 'unknown')
        username = data.get('username', 'Unknown')
        user_email = data.get('userEmail', '')
        is_admin = data.get('isAdmin', False)
        timestamp = data.get('timestamp', datetime.datetime.now().isoformat())

        print(f"  👤 User: {username}")
        print(f"  📧 Email: {user_email}")
        print(f"  👑 Admin: {is_admin}")
        print(f"  📁 Filename: {data.get('filename', 'Unknown')}")

        image_base64 = data.get('image', '')
        if not image_base64:
            return jsonify({'error': 'No image data provided'}), 400

        try:
            image_bytes = base64.b64decode(image_base64)
            print(f"✅ Image decoded: {len(image_bytes)} bytes")
        except Exception as e:
            print(f"❌ Invalid base64 image data: {str(e)}")
            return jsonify({'error': f'Invalid base64 image data: {str(e)}'}), 400

        timestamp_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        original_filename = data.get('filename', 'image.jpg')
        extension = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'jpg'
        filename = f"from_gallery_{timestamp_str}.{extension}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        with open(filepath, 'wb') as f:
            f.write(image_bytes)
        print(f"✅ Image saved: {filepath}")

        metadata = data.get('metadata', {})
        metadata.update({
            'imageName': filename,
            'uploadedAt': datetime.datetime.now().isoformat(),
            'userId': user_id,
            'username': username,
            'userEmail': user_email,
            'isAdmin': is_admin,
            'source': 'gallery_to_admin',
            'status': 'received_from_gallery',
            'timestamp': timestamp,
        })

        base_name = filename.rsplit('.', 1)[0]
        metadata_path = os.path.join(METADATA_FOLDER, f"{base_name}.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        print(f"✅ Metadata saved with username: {username}")

        received_image_entry = {
            'id': datetime.datetime.now().timestamp(),
            'filename': filename,
            'metadata': metadata,
            'image': image_base64,
            'receivedAt': datetime.datetime.now().isoformat(),
            'userId': user_id,
            'username': username,
            'userEmail': user_email,
            'isAdmin': is_admin,
        }

        with received_images_lock:
            received_images.insert(0, received_image_entry)
            if len(received_images) > MAX_RECEIVED_IMAGES:
                del received_images[MAX_RECEIVED_IMAGES:]

        threading.Thread(target=save_received_images_to_file).start()

        return jsonify({
            'success': True,
            'message': f'Image from {username} sent to admin successfully',
            'filename': filename,
            'username': username,
            'total_images': len(received_images)
        }), 200

    except Exception as e:
        print(f"❌ Send image error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ======================== 5. GET RECEIVED IMAGES (Admin Dashboard) ========================

@app.route('/api/get_received_images', methods=['GET', 'OPTIONS'])
def get_received_images():
    """Get all images sent from gallery to admin"""
    if request.method == 'OPTIONS':
        return _cors_ok()

    try:
        if not received_images:
            load_received_images_from_file()

        with received_images_lock:
            images_to_return = []
            for img in received_images[:100]:
                img_copy = img.copy()
                if 'metadata' in img_copy and img_copy['metadata']:
                    img_copy['username'] = img_copy['metadata'].get('username', 'Unknown')
                else:
                    img_copy['username'] = img_copy.get('username', 'Unknown')
                images_to_return.append(img_copy)

        return jsonify({
            'success': True,
            'count': len(images_to_return),
            'total': len(received_images),
            'images': images_to_return,
            'timestamp': datetime.datetime.now().isoformat()
        }), 200

    except Exception as e:
        print(f"❌ Get received images error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ======================== 6. GET LIVE DATA (Legacy Admin Dashboard) ========================

@app.route('/api/live_data', methods=['GET'])
def get_live_data():
    """Get all legacy live data for admin dashboard"""
    try:
        with live_data_lock:
            history = list(live_data_store)[-50:] if live_data_store else []
            data = {
                'success': True,
                'total_points': len(live_data_store),
                'latest_position': latest_drone_position,
                'history': history,
                'timestamp': datetime.datetime.now().isoformat()
            }
        return jsonify(data), 200
    except Exception as e:
        print(f"❌ Get live data error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ======================== 7. GET ALL IMAGES ========================

@app.route('/api/images', methods=['GET'])
def get_images():
    """Get list of uploaded images with metadata (flat uploads folder only)"""
    try:
        images = []
        if not os.path.exists(UPLOAD_FOLDER):
            return jsonify({'success': True, 'count': 0, 'images': images}), 200

        for filename in os.listdir(UPLOAD_FOLDER):
            full_path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isdir(full_path):
                continue  # skip operation photo subfolders — use /api/live_operations for those
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                base_name = filename.rsplit('.', 1)[0]
                metadata_path = os.path.join(METADATA_FOLDER, f"{base_name}.json")
                metadata = None
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r') as f:
                            metadata = json.load(f)
                    except Exception:
                        metadata = None

                images.append({
                    'filename': filename,
                    'url': f'/uploads/{filename}',
                    'metadata': metadata
                })

        return jsonify({'success': True, 'count': len(images), 'images': images}), 200

    except Exception as e:
        print(f"❌ Get images error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ======================== 8. SERVE UPLOADED IMAGE ========================
# Widened to <path:filepath> so it also serves operation photos, which live
# under a subfolder: /uploads/<operationId>/wp_<n>.jpg

@app.route('/uploads/<path:filepath>', methods=['GET'])
def get_uploaded_image(filepath):
    """Serve an uploaded image, flat or nested under an operation folder."""
    try:
        full_path = os.path.join(UPLOAD_FOLDER, filepath)
        # Prevent path traversal outside the uploads folder.
        if not os.path.abspath(full_path).startswith(os.path.abspath(UPLOAD_FOLDER)):
            return jsonify({'error': 'Invalid path'}), 400
        if not os.path.exists(full_path):
            return jsonify({'error': 'Image not found'}), 404
        return send_file(full_path, mimetype='image/jpeg')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ======================== 9. DELETE IMAGE ========================

@app.route('/api/delete/<filename>', methods=['DELETE'])
def delete_image(filename):
    """Delete a flat (non-operation) image and its metadata"""
    try:
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        if os.path.exists(filepath) and os.path.isfile(filepath):
            os.remove(filepath)
            print(f"✅ Deleted image: {filepath}")

        base_name = filename.rsplit('.', 1)[0]
        metadata_path = os.path.join(METADATA_FOLDER, f"{base_name}.json")
        if os.path.exists(metadata_path):
            os.remove(metadata_path)
            print(f"✅ Deleted metadata: {metadata_path}")

        with received_images_lock:
            global received_images
            received_images = [img for img in received_images if img.get('filename') != filename]

        return jsonify({'success': True, 'message': f'Deleted {filename} and its metadata'}), 200

    except Exception as e:
        print(f"❌ Delete error: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ======================== 10. CLEAR LIVE DATA (legacy) ========================

@app.route('/api/live_data/clear', methods=['POST'])
def clear_live_data():
    """Clear all legacy live data"""
    try:
        with live_data_lock:
            live_data_store.clear()
            latest_drone_position.update({
                'latitude': None, 'longitude': None, 'altitude': None,
                'distance': None, 'compass': None, 'timestamp': None,
                'droneType': None, 'status': 'idle'
            })
        save_live_data_to_file()
        return jsonify({'success': True, 'message': 'Live data cleared'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ======================== 11. CLEAR RECEIVED IMAGES ========================

@app.route('/api/received_images/clear', methods=['POST'])
def clear_received_images():
    """Clear all received images"""
    try:
        with received_images_lock:
            received_images.clear()
        save_received_images_to_file()
        return jsonify({'success': True, 'message': 'Received images cleared'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ======================== 12. LIVE OPERATIONS (pure REST — no sockets) ========================
#
# Every one of these is a plain HTTP request/response. There is no
# WebSocket, no SSE, no push channel. The admin side only ever sees new
# data when it explicitly calls GET (e.g. the person taps a refresh
# button / pulls to refresh) — nothing here pushes to the client.

@app.route('/api/live_operations/start', methods=['POST', 'OPTIONS'])
def start_live_operation():
    """Called when the user taps LIVE on Drone Ranger. Creates one operation
    with its own id + assigned color; every subsequent point/photo until
    Stop is tapped belongs to this operation."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}
    username = data.get('username', 'Unknown')

    with operations_lock:
        op_index = count_user_operations(username)
        color = assign_operation_color(username, op_index)
        operation_id = f"{secure_filename(username)}_{int(time.time() * 1000)}"

        operation = {
            'operationId': operation_id,
            'userId': data.get('userId', 'unknown'),
            'username': username,
            'userEmail': data.get('userEmail', ''),
            'isAdmin': data.get('isAdmin', False),
            'droneCategory': data.get('droneCategory', 'Custom'),
            'activeMode': data.get('activeMode', 'unknown'),
            'activeModeName': data.get('activeModeName', 'Unknown'),
            'color': color,
            'operationIndexForUser': op_index,
            'startTime': datetime.datetime.now().isoformat(),
            'endTime': None,
            'status': 'active',
            'points': [],
        }
        active_operations[operation_id] = operation
        save_operation(operation)

    print(f"🟢 Operation started: {operation_id} ({username}, color {color})")
    return jsonify({'success': True, 'operationId': operation_id, 'color': color}), 201


@app.route('/api/live_operations/<operation_id>/point', methods=['POST', 'OPTIONS'])
def add_operation_point(operation_id):
    """Adds one telemetry point to an active operation. Called every ~2s
    while streaming (or once for a manual single send)."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}

    with operations_lock:
        op = get_operation(operation_id)
        if op is None:
            return jsonify({'error': 'operation not found'}), 404
        if op['status'] != 'active':
            return jsonify({'error': 'operation is not active'}), 409

        waypoint_number = len(op['points']) + 1
        point = {
            'waypointNumber': waypoint_number,
            'timestamp': data.get('timestamp', datetime.datetime.now().isoformat()),
            'pitch': float(data.get('pitch', 0)),
            'roll': float(data.get('roll', 0)),
            'compass': float(data.get('compass', 0)),
            'distance': float(data.get('distance', 0)),
            'altitude': float(data.get('altitude', 0)),
            'drone_latitude': data.get('drone_latitude', 'N/A'),
            'drone_longitude': data.get('drone_longitude', 'N/A'),
            'user_latitude': data.get('user_latitude', 'N/A'),
            'user_longitude': data.get('user_longitude', 'N/A'),
            'zoomLevel': float(data.get('zoomLevel', 1.0)),
            'boxSize': float(data.get('boxSize', 0)),
            'imageUrl': None,
        }
        op['points'].append(point)
        save_operation(op)

    return jsonify({'success': True, 'waypointNumber': waypoint_number}), 200


@app.route('/api/live_operations/<operation_id>/photo', methods=['POST', 'OPTIONS'])
def add_operation_photo(operation_id):
    """Attaches a photo to a specific waypoint of an operation. The Flutter
    side sends the SAME waypointNumber it got back from /point for that
    tick, so the point and its photo line up."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}
    waypoint_number = int(data.get('waypointNumber', 0))
    image_b64 = data.get('image', '')
    if not image_b64:
        return jsonify({'error': 'no image data'}), 400

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception as e:
        return jsonify({'error': f'invalid base64: {e}'}), 400

    op_dir = os.path.join(UPLOAD_FOLDER, secure_filename(operation_id))
    os.makedirs(op_dir, exist_ok=True)
    filename = f'wp_{waypoint_number}.jpg'
    with open(os.path.join(op_dir, filename), 'wb') as f:
        f.write(image_bytes)

    image_url = f'/uploads/{operation_id}/{filename}'

    with operations_lock:
        op = get_operation(operation_id)
        if op:
            for p in op['points']:
                if p['waypointNumber'] == waypoint_number:
                    p['imageUrl'] = image_url
                    break
            save_operation(op)

    return jsonify({'success': True, 'imageUrl': image_url}), 200


@app.route('/api/live_operations/<operation_id>/stop', methods=['POST', 'OPTIONS'])
def stop_live_operation(operation_id):
    """Called when the user taps STOP. Finalizes the operation file."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    with operations_lock:
        op = get_operation(operation_id)
        if op is None:
            return jsonify({'error': 'operation not found'}), 404
        op['endTime'] = datetime.datetime.now().isoformat()
        op['status'] = 'completed'
        save_operation(op)
        active_operations.pop(operation_id, None)

    print(f"🔴 Operation stopped: {operation_id} ({len(op['points'])} points)")
    return jsonify({'success': True, 'operation': op}), 200


@app.route('/api/live_operations', methods=['GET'])
def list_live_operations():
    """Lightweight list for the operations picker — no point arrays, so it
    stays fast even with thousands of saved operations. Supports optional
    ?status=active and ?username=<name> filters."""
    status_filter = request.args.get('status')
    username_filter = request.args.get('username')

    operations = []
    if os.path.exists(OPERATIONS_FOLDER):
        for fname in sorted(os.listdir(OPERATIONS_FOLDER), reverse=True):
            if not fname.endswith('.json'):
                continue
            try:
                with open(os.path.join(OPERATIONS_FOLDER, fname)) as f:
                    d = json.load(f)
            except Exception:
                continue

            if status_filter and d.get('status') != status_filter:
                continue
            if username_filter and d.get('username') != username_filter:
                continue

            operations.append({
                'operationId': d['operationId'],
                'username': d['username'],
                'userId': d.get('userId'),
                'color': d.get('color'),
                'startTime': d.get('startTime'),
                'endTime': d.get('endTime'),
                'status': d.get('status'),
                'pointCount': len(d.get('points', [])),
                'droneCategory': d.get('droneCategory'),
                'activeModeName': d.get('activeModeName'),
            })

    return jsonify({'success': True, 'count': len(operations), 'operations': operations}), 200


@app.route('/api/live_operations/<operation_id>', methods=['GET'])
def get_live_operation_detail(operation_id):
    """Full operation detail including all points (each with its imageUrl),
    for the table/map pages."""
    op = get_operation(operation_id)
    if op is None:
        return jsonify({'error': 'operation not found'}), 404
    return jsonify({'success': True, 'operation': op}), 200


@app.route('/api/live_operations/<operation_id>', methods=['DELETE', 'OPTIONS'])
def delete_live_operation(operation_id):
    """Deletes an operation's record file and its whole photo folder."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    with operations_lock:
        op = get_operation(operation_id)
        active_operations.pop(operation_id, None)

    deleted_file = False
    path = operation_file_path(operation_id)
    if os.path.exists(path):
        try:
            os.remove(path)
            deleted_file = True
        except Exception as e:
            print(f"❌ Error deleting operation file {operation_id}: {e}")

    deleted_photos = 0
    op_dir = os.path.join(UPLOAD_FOLDER, secure_filename(operation_id))
    if os.path.isdir(op_dir):
        try:
            for fname in os.listdir(op_dir):
                fpath = os.path.join(op_dir, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    deleted_photos += 1
            os.rmdir(op_dir)
        except Exception as e:
            print(f"❌ Error deleting operation photos {operation_id}: {e}")

    if op is None and not deleted_file and deleted_photos == 0:
        return jsonify({'error': 'operation not found'}), 404

    print(f"🗑️ Deleted operation: {operation_id} ({deleted_photos} photos)")
    return jsonify({'success': True, 'operationId': operation_id, 'deletedPhotos': deleted_photos}), 200


@app.route('/api/live_operations/clear', methods=['POST', 'OPTIONS'])
def clear_live_operations():
    """Deletes ALL saved operations and their photos. For admin/testing
    cleanup — added for parity with /api/live_data/clear and
    /api/received_images/clear. Not wired to any button in the app yet."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    deleted = 0
    with operations_lock:
        active_operations.clear()
        if os.path.exists(OPERATIONS_FOLDER):
            for fname in os.listdir(OPERATIONS_FOLDER):
                if fname.endswith('.json'):
                    try:
                        os.remove(os.path.join(OPERATIONS_FOLDER, fname))
                        deleted += 1
                    except Exception as e:
                        print(f"❌ Error deleting {fname}: {e}")

    if os.path.exists(UPLOAD_FOLDER):
        for name in os.listdir(UPLOAD_FOLDER):
            full = os.path.join(UPLOAD_FOLDER, name)
            if os.path.isdir(full):
                try:
                    for fname in os.listdir(full):
                        os.remove(os.path.join(full, fname))
                    os.rmdir(full)
                except Exception as e:
                    print(f"❌ Error clearing operation folder {name}: {e}")

    return jsonify({'success': True, 'deletedOperations': deleted}), 200


# ======================== 13. HEALTH CHECK ========================

@app.route('/health', methods=['GET'])
def health_check():
    op_count = 0
    if os.path.exists(OPERATIONS_FOLDER):
        op_count = len([f for f in os.listdir(OPERATIONS_FOLDER) if f.endswith('.json')])
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.datetime.now().isoformat(),
        'upload_folder': UPLOAD_FOLDER,
        'metadata_folder': METADATA_FOLDER,
        'operations_folder': OPERATIONS_FOLDER,
        'live_data_points': len(live_data_store),
        'received_images': len(received_images),
        'active_operations': len(active_operations),
        'total_operations': op_count,
        'upload_folder_exists': os.path.exists(UPLOAD_FOLDER),
        'metadata_folder_exists': os.path.exists(METADATA_FOLDER),
        'database_configured': bool(DATABASE_URL),
    }), 200


# ======================== 14. AUTH (POSTGRES + OTP LOGIN) ========================

@app.route('/api/auth/request-otp', methods=['POST', 'OPTIONS'])
def request_otp():
    """Person enters their email → we confirm the account exists and
    (for now) just print the fixed OTP to the server logs instead of
    actually sending it anywhere."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id FROM users WHERE email = %s', (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

    if user is None:
        return jsonify({'success': False, 'message': 'No account found with this email'}), 404

    print(f'📩 [TEMP OTP] Code for {email}: {TEMP_OTP}')
    return jsonify({'success': True, 'message': f'OTP sent to {email}'}), 200


@app.route('/api/auth/verify-otp', methods=['POST', 'OPTIONS'])
def verify_otp():
    """Person enters the OTP → checked against the fixed TEMP_OTP value.
    On success, returns the user's profile (email, displayName, role).

    Device lock: the client sends a deviceId (a random ID generated once
    on first app launch, persisted locally — NOT a network IP, since
    those change constantly). The FIRST successful login for an account
    binds it to that deviceId. Every login after that must send the same
    deviceId, or it's rejected — so a stolen/shared email+OTP can't be
    used to log the same account in from a different phone."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    otp = (data.get('otp') or '').strip()
    device_id = (data.get('deviceId') or '').strip()

    if not email or not otp:
        return jsonify({'success': False, 'message': 'Email and OTP are required'}), 400
    if not device_id:
        return jsonify({'success': False, 'message': 'Missing device ID'}), 400

    if otp != TEMP_OTP:
        return jsonify({'success': False, 'message': 'Invalid OTP'}), 401

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cur.fetchone()
        if user is None:
            cur.close()
            conn.close()
            return jsonify({'success': False, 'message': 'No account found with this email'}), 404

        existing_device = user['device_id']

        if existing_device is None:
            # First login ever for this account — bind it to this device.
            cur.execute(
                'UPDATE users SET device_id = %s, last_login = NOW() WHERE email = %s',
                (device_id, email)
            )
            conn.commit()
        elif existing_device != device_id:
            # Bound to a DIFFERENT device already — reject.
            cur.close()
            conn.close()
            return jsonify({
                'success': False,
                'message': 'This account is already signed in on another device. Contact an admin to reset it.'
            }), 403
        else:
            # Same device as before — normal login.
            cur.execute('UPDATE users SET last_login = NOW() WHERE email = %s', (email,))
            conn.commit()

        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

    return jsonify({
        'success': True,
        'message': 'Login successful',
        'user': {
            'id': user['id'],
            'email': user['email'],
            'displayName': user['display_name'],
            'role': user['role'],
        }
    }), 200


@app.route('/api/auth/users', methods=['GET'])
def list_users():
    """List all accounts — admin/debug use. device_id shows which phone
    (if any) each account is currently locked to."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id, email, display_name, role, device_id, created_at, last_login FROM users ORDER BY id')
        users = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'count': len(users), 'users': users}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/auth/users/<int:user_id>', methods=['GET', 'OPTIONS'])
def get_user(user_id):
    """Fetch one user's details. Complements PUT/DELETE below — the admin
    control panel calls this to populate the edit screen."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            'SELECT id, email, display_name, role, device_id, created_at, last_login '
            'FROM users WHERE id = %s',
            (user_id,)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

    if user is None:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    return jsonify({'success': True, 'user': user}), 200

# @app.route('/api/auth/users/reset-device', methods=['POST', 'OPTIONS'])
# def reset_user_device():
#     """Clears the device lock for one account (e.g. they got a new phone,
#     or you're testing). The next OTP login from ANY device will re-bind.
#     Admin/debug use — lock this down once you have real admin auth."""
#     if request.method == 'OPTIONS':
#         return _cors_ok()

#     data = request.get_json() or {}
#     email = (data.get('email') or '').strip().lower()
#     if not email:
#         return jsonify({'success': False, 'message': 'Email is required'}), 400

#     try:
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute(
#             'UPDATE users SET device_id = NULL WHERE email = %s RETURNING id',
#             (email,)
#         )
#         row = cur.fetchone()
#         conn.commit()
#         cur.close()
#         conn.close()
#     except Exception as e:
#         return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

#     if row is None:
#         return jsonify({'success': False, 'message': 'No account found with this email'}), 404

#     return jsonify({'success': True, 'message': f'Device lock cleared for {email}'}), 200
@app.route('/api/auth/users/reset-device', methods=['POST', 'OPTIONS'])
def reset_user_device():
    """Clears the device lock for one account. Accepts either
    {'email': '...'} or {'userId': 2} so the app can send whichever
    it has handy."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    user_id = data.get('userId') or data.get('id')

    if not email and not user_id:
        return jsonify({'success': False, 'message': 'Email or userId is required'}), 400

    try:
        conn = get_db()
        cur = conn.cursor()

        if email:
            cur.execute(
                'UPDATE users SET device_id = NULL WHERE email = %s RETURNING id, email',
                (email,)
            )
        else:
            cur.execute(
                'UPDATE users SET device_id = NULL WHERE id = %s RETURNING id, email',
                (int(user_id),)
            )

        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

    if row is None:
        return jsonify({'success': False, 'message': 'No matching account found'}), 404

    return jsonify({
        'success': True,
        'message': f"Device lock cleared for {row['email']}",
    }), 200

@app.route('/api/auth/users', methods=['POST', 'OPTIONS'])
def create_user():
    """Add a new account — admin/debug use while login data is static.
    Lock this down (or remove it) once you have real admin auth in front
    of it."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    display_name = (data.get('displayName') or email.split('@')[0]).strip()
    role = (data.get('role') or 'user').strip()

    if not email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO users (email, display_name, role) VALUES (%s, %s, %s) '
            'ON CONFLICT (email) DO NOTHING RETURNING id',
            (email, display_name, role)
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

    if row is None:
        return jsonify({'success': False, 'message': 'That email is already registered'}), 409

    return jsonify({'success': True, 'message': 'User created', 'id': row['id']}), 201


@app.route('/api/auth/users/<int:user_id>', methods=['PUT', 'PATCH', 'OPTIONS'])
def update_user(user_id):
    """Edit an existing account's email / displayName / role. Send only
    the fields you want to change — anything omitted stays as-is.
    Admin/debug use — lock this down once you have real admin auth."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}
    fields = []
    values = []

    if 'email' in data:
        fields.append('email = %s')
        values.append((data.get('email') or '').strip().lower())
    if 'displayName' in data:
        fields.append('display_name = %s')
        values.append((data.get('displayName') or '').strip())
    if 'role' in data:
        fields.append('role = %s')
        values.append((data.get('role') or 'user').strip())

    if not fields:
        return jsonify({'success': False, 'message': 'Nothing to update — send email, displayName and/or role'}), 400

    values.append(user_id)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            f'UPDATE users SET {", ".join(fields)} WHERE id = %s '
            f'RETURNING id, email, display_name, role, device_id',
            tuple(values)
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        # Most likely cause: the new email collides with another account
        # (UNIQUE constraint) — surfaced as a plain error string either way.
        return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

    if row is None:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    return jsonify({'success': True, 'message': 'User updated', 'user': row}), 200


@app.route('/api/auth/users/<int:user_id>', methods=['DELETE', 'OPTIONS'])
def delete_user(user_id):
    """Permanently deletes one account. Admin/debug use — lock this down
    once you have real admin auth."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM users WHERE id = %s RETURNING id, email', (user_id,))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

    if row is None:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    return jsonify({'success': True, 'message': f"Deleted {row['email']}"}), 200


@app.route('/api/auth/reset', methods=['POST', 'OPTIONS'])
def reset_auth():
    """DESTRUCTIVE: wipes every account (including anything you created
    or edited) and re-seeds just the 4 static accounts from scratch, with
    fresh (empty) device locks. Handy while testing so you can get back
    to a known-clean state in one call. No confirmation step — don't wire
    this to a casual button once real users exist."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('DELETE FROM users')
        for u in STATIC_USERS:
            cur.execute(
                'INSERT INTO users (email, password, display_name, role) '
                'VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING',
                (u['email'], u['password'], u['displayName'], u['role'])
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {e}'}), 500

    return jsonify({
        'success': True,
        'message': f'Reset complete — {len(STATIC_USERS)} static users reseeded, all device locks cleared'
    }), 200


# ======================== 15. INDEX / API INFO ========================

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'name': 'Drone Ranger API',
        'version': '3.1.0',
        'endpoints': [
            {'path': '/', 'method': 'GET', 'description': 'API info'},
            {'path': '/health', 'method': 'GET', 'description': 'Health check'},
            {'path': '/api/upload_drone_image', 'method': 'POST', 'description': 'Upload image with metadata'},
            {'path': '/api/send_drone_data', 'method': 'POST', 'description': 'Legacy: send one-off drone data'},
            {'path': '/api/send_live_data', 'method': 'POST', 'description': 'Legacy fallback: single live data send'},
            {'path': '/api/send_drone_image', 'method': 'POST', 'description': 'Send image from gallery to admin'},
            {'path': '/api/get_received_images', 'method': 'GET', 'description': 'Get images sent to admin'},
            {'path': '/api/live_data', 'method': 'GET', 'description': 'Legacy: get flat live data (poll on demand, no push)'},
            {'path': '/api/live_data/clear', 'method': 'POST', 'description': 'Legacy: clear live data'},
            {'path': '/api/received_images/clear', 'method': 'POST', 'description': 'Clear received images'},
            {'path': '/api/images', 'method': 'GET', 'description': 'Get all flat images'},
            {'path': '/uploads/<path:filepath>', 'method': 'GET', 'description': 'Get uploaded image (flat or per-operation)'},
            {'path': '/api/delete/<filename>', 'method': 'DELETE', 'description': 'Delete a flat image'},
            {'path': '/api/live_operations/start', 'method': 'POST', 'description': 'Start a new live operation (tap LIVE)'},
            {'path': '/api/live_operations/<id>/point', 'method': 'POST', 'description': 'Add a telemetry point to an operation'},
            {'path': '/api/live_operations/<id>/photo', 'method': 'POST', 'description': 'Attach a photo to a waypoint'},
            {'path': '/api/live_operations/<id>/stop', 'method': 'POST', 'description': 'Stop and finalize an operation (tap STOP)'},
            {'path': '/api/live_operations', 'method': 'GET', 'description': 'List all operations (summary)'},
            {'path': '/api/live_operations/<id>', 'method': 'GET', 'description': 'Get full operation detail + points'},
            {'path': '/api/live_operations/<id>', 'method': 'DELETE', 'description': 'Delete an operation + its photos'},
            {'path': '/api/live_operations/clear', 'method': 'POST', 'description': 'Delete ALL operations + photos'},
            {'path': '/api/auth/request-otp', 'method': 'POST', 'description': 'Step 1: request OTP for an email (Postgres-backed)'},
            {'path': '/api/auth/verify-otp', 'method': 'POST', 'description': 'Step 2: verify OTP and log in'},
            {'path': '/api/auth/users', 'method': 'GET', 'description': 'List all user accounts (includes device lock status)'},
            {'path': '/api/auth/users', 'method': 'POST', 'description': 'Create a new user account'},
            {'path': '/api/auth/users/<id>', 'method': 'PUT', 'description': 'Edit a user (email/displayName/role)'},
            {'path': '/api/auth/users/<id>', 'method': 'DELETE', 'description': 'Delete a user account'},
            {'path': '/api/auth/users/reset-device', 'method': 'POST', 'description': 'Clear a device lock (e.g. user got a new phone)'},
            {'path': '/api/auth/reset', 'method': 'POST', 'description': 'DESTRUCTIVE: wipe all users, reseed the 4 static accounts'},
        ]
    }), 200


# ======================== LOAD DATA ON STARTUP ========================
load_live_data_from_file()
load_received_images_from_file()
init_auth_db()

# Start the background sweeper that auto-closes stale "active" operations
# (e.g. app crashed mid-stream without hitting Stop).
threading.Thread(target=stale_active_operation_sweeper, daemon=True).start()

print("=" * 50)
print("🚀 Drone Ranger API Server Started")
print(f"📁 Upload folder: {UPLOAD_FOLDER}")
print(f"📁 Metadata folder: {METADATA_FOLDER}")
print(f"📁 Operations folder: {OPERATIONS_FOLDER}")
print(f"📊 Live data points: {len(live_data_store)}")
print(f"🖼️ Received images: {len(received_images)}")
print(f"🔐 Database configured: {bool(DATABASE_URL)}")
print("=" * 50)

# ======================== FOR RENDER / PYTHONANYWHERE ========================
# DO NOT use app.run() on Render or PythonAnywhere — both use a WSGI
# server (gunicorn on Render) that imports `app` directly from this file.

# If you want to test locally, uncomment the line below:
# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=5001)