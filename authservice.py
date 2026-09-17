# =====================================================================
# AUTH ROUTES — paste this whole block into main.py
#
# WHERE TO PASTE: right after your existing imports/config section, and
# BEFORE the "# ======================== LOAD DATA ON STARTUP ========"
# section near the bottom of your file (so `app` already exists above
# this block, and init_auth_db() can be called alongside your other
# startup loaders below).
#
# ALSO ADD TO requirements.txt:
#   psycopg2-binary==2.9.9
#
# ALSO ADD ON RENDER (see the setup guide in chat):
#   - Create a Postgres instance
#   - Add DATABASE_URL as an environment variable on your web service
# =====================================================================

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL', '')
# Render (and some other hosts) hand out "postgres://..." but psycopg2's
# newer versions want "postgresql://..." — normalize it either way.
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# TEMPORARY: fixed OTP for every login attempt. Replace this with a real
# SMS/email OTP provider (Twilio, SES, etc.) later — search for TEMP_OTP
# in this file when you're ready to wire that in.
TEMP_OTP = '1234'

# "login data will static" — same 4 accounts you had hardcoded in the old
# Flutter AuthService, now seeded into Postgres once on first startup.
STATIC_USERS = [
    {'email': 'superadmin@system.com', 'password': 'securepass', 'displayName': 'System Admin', 'role': 'superadmin'},
    {'email': 'company@company.com', 'password': 'securepass', 'displayName': 'Company Admin', 'role': 'companyadmin'},
    {'email': 'controller@drone.com', 'password': 'securepass', 'displayName': 'Drone Controller', 'role': 'controller'},
    {'email': 'user1@drone.com', 'password': 'securepass', 'displayName': 'User1', 'role': 'user'},
    {'email': 'user2@drone.com', 'password': 'securepass', 'displayName': 'User2', 'role': 'user'},
    {'email': 'user3@drone.com', 'password': 'securepass', 'displayName': 'User3', 'role': 'user'},
    {'email': 'user4@drone.com', 'password': 'securepass', 'displayName': 'User4', 'role': 'user'},
    {'email': 'user5@drone.com', 'password': 'securepass', 'displayName': 'User5', 'role': 'user'},
    {'email': 'user6@drone.com', 'password': 'securepass', 'displayName': 'User6', 'role': 'user'},
    {'email': 'user7@drone.com', 'password': 'securepass', 'displayName': 'User7', 'role': 'user'},
    {'email': 'user8@drone.com', 'password': 'securepass', 'displayName': 'User8', 'role': 'user'},
    {'email': 'user9@drone.com', 'password': 'securepass', 'displayName': 'User9', 'role': 'user'},
    {'email': 'user10@drone.com', 'password': 'securepass', 'displayName': 'User10', 'role': 'user'},
    {'email': 'user11@drone.com', 'password': 'securepass', 'displayName': 'User11', 'role': 'user'},
    {'email': 'user12@drone.com', 'password': 'securepass', 'displayName': 'User12', 'role': 'user'},
    {'email': 'user13@drone.com', 'password': 'securepass', 'displayName': 'User13', 'role': 'user'},
    {'email': 'user14@drone.com', 'password': 'securepass', 'displayName': 'User14', 'role': 'user'},
    {'email': 'user15@drone.com', 'password': 'securepass', 'displayName': 'User15', 'role': 'user'},
    {'email': 'user16@drone.com', 'password': 'securepass', 'displayName': 'User16', 'role': 'user'},
    {'email': 'user17@drone.com', 'password': 'securepass', 'displayName': 'User17', 'role': 'user'},
    {'email': 'user18@drone.com', 'password': 'securepass', 'displayName': 'User18', 'role': 'user'},
    {'email': 'user19@drone.com', 'password': 'securepass', 'displayName': 'User19', 'role': 'user'},
    {'email': 'user20@drone.com', 'password': 'securepass', 'displayName': 'User20', 'role': 'user'},
    {'email': 'user21@drone.com', 'password': 'securepass', 'displayName': 'User21', 'role': 'user'},
    {'email': 'user22@drone.com', 'password': 'securepass', 'displayName': 'User22', 'role': 'user'},
    {'email': 'user23@drone.com', 'password': 'securepass', 'displayName': 'User23', 'role': 'user'},
    {'email': 'user24@drone.com', 'password': 'securepass', 'displayName': 'User24', 'role': 'user'},
    {'email': 'user25@drone.com', 'password': 'securepass', 'displayName': 'User25', 'role': 'user'}



]


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


# ======================== AUTH: STEP 1 — REQUEST OTP ========================

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


# ======================== AUTH: STEP 2 — VERIFY OTP ========================

@app.route('/api/auth/verify-otp', methods=['POST', 'OPTIONS'])
def verify_otp():
    """Person enters the OTP → checked against the fixed TEMP_OTP value.
    On success, returns the user's profile (email, displayName, role)."""
    if request.method == 'OPTIONS':
        return _cors_ok()

    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    otp = (data.get('otp') or '').strip()

    if not email or not otp:
        return jsonify({'success': False, 'message': 'Email and OTP are required'}), 400

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


# ======================== AUTH: LIST USERS (admin/debug) ========================

@app.route('/api/auth/users', methods=['GET'])
def list_users():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id, email, display_name, role, created_at, last_login FROM users ORDER BY id')
        users = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({'success': True, 'count': len(users), 'users': users}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ======================== AUTH: ADD A NEW USER (admin/debug) ========================
# Handy while "login data will static" — lets you add accounts via curl
# instead of writing SQL by hand. Lock this down (or remove it) once
# you have real admin auth in front of it.

@app.route('/api/auth/users', methods=['POST', 'OPTIONS'])
def create_user():
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