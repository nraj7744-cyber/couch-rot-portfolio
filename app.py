from flask import Flask, send_from_directory, request, jsonify
import os
import time
import urllib.parse as urlparse
import sqlite3

app = Flask(__name__, static_folder='public', static_url_path='')

START_TIME = time.time()

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        import psycopg2
        url = urlparse.urlparse(db_url)
        dbname = url.path[1:]
        user = url.username
        password = url.password
        host = url.hostname
        port = url.port
        conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port
        )
        return conn, True
    else:
        conn = sqlite3.connect('database.db')
        return conn, False

def init_db():
    conn, is_postgres = get_db_connection()
    cursor = conn.cursor()
    
    if is_postgres:
        # PostgreSQL Schema
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS void_messages (
                id SERIAL PRIMARY KEY,
                name TEXT,
                email TEXT,
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS apathy_stats (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dreams_votes (
                dream_id TEXT PRIMARY KEY,
                votes_yes INTEGER DEFAULT 0,
                votes_no INTEGER DEFAULT 0
            )
        """)
        # Initialize rows if they don't exist
        cursor.execute("INSERT INTO apathy_stats (key, value) VALUES ('clicks', 0) ON CONFLICT (key) DO NOTHING")
        for d_id in ['DREAM_001', 'DREAM_002', 'DREAM_003']:
            cursor.execute("INSERT INTO dreams_votes (dream_id, votes_yes, votes_no) VALUES (%s, 0, 0) ON CONFLICT (dream_id) DO NOTHING", (d_id,))
    else:
        # SQLite Schema
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS void_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS apathy_stats (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dreams_votes (
                dream_id TEXT PRIMARY KEY,
                votes_yes INTEGER DEFAULT 0,
                votes_no INTEGER DEFAULT 0
            )
        """)
        # Initialize rows if they don't exist
        cursor.execute("INSERT OR IGNORE INTO apathy_stats (key, value) VALUES ('clicks', 0)")
        for d_id in ['DREAM_001', 'DREAM_002', 'DREAM_003']:
            cursor.execute("INSERT OR IGNORE INTO dreams_votes (dream_id, votes_yes, votes_no) VALUES (?, 0, 0)", (d_id,))
            
    conn.commit()
    conn.close()

# Initialize DB on import/startup
try:
    init_db()
except Exception as e:
    print(f"Database initialization failed: {e}")

def execute_db(query, args=()):
    conn, is_postgres = get_db_connection()
    if is_postgres:
        query = query.replace('?', '%s')
    cursor = conn.cursor()
    cursor.execute(query, args)
    conn.commit()
    conn.close()

def query_db(query, args=(), one=False):
    conn, is_postgres = get_db_connection()
    if is_postgres:
        query = query.replace('?', '%s')
    cursor = conn.cursor()
    cursor.execute(query, args)
    rv = cursor.fetchall()
    
    col_names = [desc[0] for desc in cursor.description] if cursor.description else []
    conn.commit()
    conn.close()
    
    results = [dict(zip(col_names, row)) for row in rv]
    return (results[0] if results else None) if one else results

# Helper to format server uptime
def get_formatted_uptime():
    elapsed = time.time() - START_TIME
    hours = elapsed / 3600
    if hours < 0.1:
        minutes = elapsed / 60
        return f"{minutes:.1f} mins"
    return f"{hours:.2f} hrs"

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

# Serve static frontend
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(app.static_folder, path)

# ── API ENDPOINTS ───────────────────────────────────────

# GET /api/apathy - fetch current apathy stats
@app.route('/api/apathy', methods=['GET'])
def get_apathy():
    try:
        row = query_db("SELECT value FROM apathy_stats WHERE key = 'clicks'", one=True)
        clicks = row['value'] if row else 0
        return jsonify({
            "clicks": clicks,
            "uptime_str": get_formatted_uptime(),
            "uptime_sec": int(time.time() - START_TIME)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# POST /api/apathy/rot - increment global rot clicks
@app.route('/api/apathy/rot', methods=['POST'])
def post_apathy_rot():
    try:
        execute_db("UPDATE apathy_stats SET value = value + 1 WHERE key = 'clicks'")
        row = query_db("SELECT value FROM apathy_stats WHERE key = 'clicks'", one=True)
        clicks = row['value'] if row else 0
        return jsonify({
            "success": True,
            "clicks": clicks,
            "uptime_str": get_formatted_uptime()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# GET /api/void-messages - fetch recent messages sent to the void
@app.route('/api/void-messages', methods=['GET'])
def get_void_messages():
    try:
        rows = query_db("SELECT name, message, timestamp FROM void_messages ORDER BY id DESC LIMIT 15")
        # Format timestamps nicely for display
        messages = []
        for r in rows:
            ts = r['timestamp']
            # Postgres timestamp vs SQLite text string parsing
            if not isinstance(ts, str):
                ts = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                # SQLite datetime format clean up if necessary (e.g. remove milliseconds)
                ts = ts.split('.')[0] if '.' in ts else ts
            messages.append({
                "name": r['name'],
                "message": r['message'],
                "timestamp": ts
            })
        return jsonify(messages)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# POST /api/void-messages - send message to the void
@app.route('/api/void-messages', methods=['POST'])
def post_void_message():
    try:
        data = request.json or {}
        name = data.get('name', 'Anonymous Lurker').strip() or 'Anonymous Lurker'
        email = data.get('email', 'void@domain.com').strip() or 'void@domain.com'
        message = data.get('message', 'No message provided.').strip() or 'No message provided.'
        
        execute_db(
            "INSERT INTO void_messages (name, email, message) VALUES (?, ?, ?)",
            (name, email, message)
        )
        return jsonify({"success": True, "message": "Message saved to the database void log."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# GET /api/dreams - fetch votes for dream cards
@app.route('/api/dreams', methods=['GET'])
def get_dreams():
    try:
        rows = query_db("SELECT dream_id, votes_yes, votes_no FROM dreams_votes")
        votes = {}
        for r in rows:
            votes[r['dream_id']] = {
                "yes": r['votes_yes'],
                "no": r['votes_no']
            }
        return jsonify(votes)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# POST /api/dreams/<dream_id>/vote - vote on a dream
@app.route('/api/dreams/<dream_id>/vote', methods=['POST'])
def post_dream_vote(dream_id):
    try:
        data = request.json or {}
        vote = data.get('vote')
        if vote not in ['yes', 'no']:
            return jsonify({"error": "Invalid vote parameter. Must be 'yes' or 'no'."}), 400
            
        if dream_id not in ['DREAM_001', 'DREAM_002', 'DREAM_003']:
            return jsonify({"error": "Invalid dream_id."}), 404
            
        col = 'votes_yes' if vote == 'yes' else 'votes_no'
        execute_db(f"UPDATE dreams_votes SET {col} = {col} + 1 WHERE dream_id = ?", (dream_id,))
        
        row = query_db("SELECT votes_yes, votes_no FROM dreams_votes WHERE dream_id = ?", (dream_id,), one=True)
        return jsonify({
            "success": True,
            "dream_id": dream_id,
            "votes": {
                "yes": row['votes_yes'] if row else 0,
                "no": row['votes_no'] if row else 0
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
