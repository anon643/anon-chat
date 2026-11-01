from flask import Flask, render_template, request, redirect, url_for, make_response, jsonify
import sqlite3
import secrets
import time

app = Flask(__name__)
DB_NAME = "chat.db"

# ---------- База данных ----------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS queue (
            token TEXT PRIMARY KEY,
            joined_at REAL NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pairs (
            token TEXT PRIMARY KEY,
            partner TEXT NOT NULL,
            room TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL,
            sender TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- Анонимный токен ----------
def get_token():
    token = request.cookies.get("anon_token")
    if not token:
        token = secrets.token_hex(16)
    return token

def set_token_cookie(response, token):
    response.set_cookie("anon_token", token, max_age=60*60*24*365, httponly=True)
    return response

# ---------- Главное меню ----------
@app.route('/')
def menu():
    token = get_token()
    response = make_response(render_template('menu.html'))
    return set_token_cookie(response, token)

# ---------- Начать поиск ----------
@app.route('/search')
def search():
    token = get_token()
    conn = get_db()

    pair = conn.execute("SELECT * FROM pairs WHERE token = ?", (token,)).fetchone()
    if pair:
        conn.close()
        response = make_response(redirect(url_for('chat')))
        return set_token_cookie(response, token)

    waiting = conn.execute(
        "SELECT token FROM queue WHERE token != ? ORDER BY joined_at LIMIT 1",
        (token,)
    ).fetchone()

    if waiting:
        partner = waiting['token']
        room = secrets.token_hex(8)
        conn.execute("INSERT OR REPLACE INTO pairs (token, partner, room) VALUES (?, ?, ?)", (token, partner, room))
        conn.execute("INSERT OR REPLACE INTO pairs (token, partner, room) VALUES (?, ?, ?)", (partner, token, room))
        conn.execute("DELETE FROM queue WHERE token IN (?, ?)", (token, partner))
        conn.commit()
        conn.close()
        response = make_response(redirect(url_for('chat')))
        return set_token_cookie(response, token)

    conn.execute("INSERT OR REPLACE INTO queue (token, joined_at) VALUES (?, ?)", (token, time.time()))
    conn.commit()
    conn.close()
    response = make_response(render_template('chat.html', waiting=True))
    return set_token_cookie(response, token)

# ---------- Страница чата ----------
@app.route('/chat')
def chat():
    token = get_token()
    conn = get_db()
    pair = conn.execute("SELECT * FROM pairs WHERE token = ?", (token,)).fetchone()
    conn.close()

    if not pair:
        response = make_response(render_template('chat.html', waiting=True))
        return set_token_cookie(response, token)

    response = make_response(render_template('chat.html', waiting=False, room=pair['room']))
    return set_token_cookie(response, token)

# ---------- Проверка статуса ----------
@app.route('/status')
def status():
    token = get_token()
    conn = get_db()
    pair = conn.execute("SELECT * FROM pairs WHERE token = ?", (token,)).fetchone()
    conn.close()

    if pair:
        return jsonify({"status": "paired", "room": pair['room']})
    else:
        return jsonify({"status": "waiting"})

# ---------- Отправить сообщение ----------
@app.route('/send', methods=['POST'])
def send():
    token = get_token()
    text = request.form.get('text', '').strip()
    if not text:
        return jsonify({"ok": False})

    conn = get_db()
    pair = conn.execute("SELECT * FROM pairs WHERE token = ?", (token,)).fetchone()
    if not pair:
        conn.close()
        return jsonify({"ok": False, "error": "no_pair"})

    conn.execute(
        "INSERT INTO messages (room, sender, text, created_at) VALUES (?, ?, ?, ?)",
        (pair['room'], token, text, time.time())
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ---------- Получить сообщения ----------
@app.route('/messages')
def messages():
    token = get_token()
    conn = get_db()
    pair = conn.execute("SELECT * FROM pairs WHERE token = ?", (token,)).fetchone()
    if not pair:
        conn.close()
        return jsonify({"messages": []})

    rows = conn.execute(
        "SELECT sender, text, created_at FROM messages WHERE room = ? ORDER BY id",
        (pair['room'],)
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "mine": r['sender'] == token,
            "text": r['text'],
            "time": r['created_at']
        })
    return jsonify({"messages": result})

# ---------- Выйти ----------
@app.route('/leave')
def leave():
    token = get_token()
    conn = get_db()
    pair = conn.execute("SELECT * FROM pairs WHERE token = ?", (token,)).fetchone()
    if pair:
        partner = pair['partner']
        room = pair['room']
        conn.execute("DELETE FROM pairs WHERE token IN (?, ?)", (token, partner))
        conn.execute("DELETE FROM messages WHERE room = ?", (room,))
        conn.execute("DELETE FROM queue WHERE token = ?", (token,))
        conn.commit()
    conn.close()
    response = make_response(redirect(url_for('menu')))
    return set_token_cookie(response, token)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)