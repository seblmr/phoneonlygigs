from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import sqlite3
from datetime import datetime, timedelta
import stripe
import os
import json
import time
from collections import defaultdict
from functools import wraps

app = Flask(__name__)
# FIX: secret key nécessaire pour les sessions Flask
app.secret_key = os.getenv('SECRET_KEY', 'change-this-in-production')

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')


# ── DB ──────────────────────────────────────────────────────────────────────

def get_db():
    # FIX: row_factory → accès par nom (job['title']) au lieu de job[1]
    conn = sqlite3.connect('jobs.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id          INTEGER PRIMARY KEY,
        title       TEXT,
        company     TEXT,
        description TEXT,
        niche       TEXT,
        budget      TEXT,
        contact     TEXT,
        date        TEXT
    )''')
    # FIX: table d'idempotence pour éviter les doublons au rechargement de /success
    c.execute('''CREATE TABLE IF NOT EXISTS processed_sessions (
        session_id   TEXT PRIMARY KEY,
        processed_at TEXT
    )''')
    conn.commit()
    conn.close()


init_db()


def get_gigs_this_week():
    conn = get_db()
    c = conn.cursor()
    # FIX: format ISO YYYY-MM-DD → comparaison de chaînes fiable
    one_week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(*) FROM jobs WHERE date >= ?", (one_week_ago,))
    count = c.fetchone()[0]
    conn.close()
    return count


# ── Rate limiter léger (sans dépendance externe) ─────────────────────────────

_rate_store: dict = defaultdict(list)


def rate_limit(max_calls: int, period: int):
    """Décorateur : max_calls requêtes par period secondes par IP."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr
            now = time.time()
            _rate_store[ip] = [t for t in _rate_store[ip] if now - t < period]
            if len(_rate_store[ip]) >= max_calls:
                return jsonify({"error": "Too many requests. Try again later."}), 429
            _rate_store[ip].append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Auth admin via session (plus sûr que la clé dans l'URL) ─────────────────

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return wrapper


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        key = request.form.get('key', '')
        if key == os.getenv('ADMIN_KEY'):
            session['is_admin'] = True
            return redirect(url_for('admin'))
        error = 'Mauvaise clé.'
    return render_template('admin_login.html', error=error)


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect('/')


# ── Routes publiques ─────────────────────────────────────────────────────────

@app.route('/')
def index():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = c.fetchall()
    conn.close()
    weekly_count = get_gigs_this_week()
    return render_template('index.html', jobs=jobs, weekly_count=weekly_count)


@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    title       = request.form['title']
    company     = request.form['company']
    description = request.form['description']
    niche       = request.form['niche']
    budget      = request.form['budget']
    contact     = request.form['contact']

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Post a gig on PhoneOnlyGigs',
                        'description': 'Your gig will be live instantly after payment',
                    },
                    'unit_amount': 2900,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://phoneonlygigs.com/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://phoneonlygigs.com/post',
            metadata={
                'job_data': json.dumps({
                    'title':       title,
                    'company':     company,
                    'description': description,
                    'niche':       niche,
                    'budget':      budget,
                    'contact':     contact,
                })
            }
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return f"Error: {str(e)}", 400


@app.route('/success')
def success():
    session_id = request.args.get('session_id')
    if not session_id:
        return redirect('/')

    conn = get_db()
    c = conn.cursor()

    try:
        # FIX: idempotence — on vérifie si cette session Stripe a déjà été traitée
        c.execute("SELECT session_id FROM processed_sessions WHERE session_id = ?", (session_id,))
        if c.fetchone():
            conn.close()
            return render_template('success.html')  # page de confirmation sans réinsérer

        stripe_session = stripe.checkout.Session.retrieve(session_id)
        if stripe_session.payment_status == 'paid':
            job_data = json.loads(stripe_session.metadata['job_data'])

            c.execute(
                """INSERT INTO jobs (title, company, description, niche, budget, contact, date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_data['title'], job_data['company'], job_data['description'],
                    job_data['niche'], job_data['budget'], job_data['contact'],
                    datetime.now().strftime('%Y-%m-%d'),  # FIX: format ISO
                )
            )
            # FIX: on marque la session comme traitée
            c.execute(
                "INSERT INTO processed_sessions (session_id, processed_at) VALUES (?, ?)",
                (session_id, datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            return render_template('success.html')

    except Exception as e:
        print(f"[/success] Error: {e}")

    conn.close()
    return redirect('/')


@app.route('/post', methods=['GET'])
def post_job_get():
    return render_template('post.html')


@app.route('/job/<int:job_id>')
def job_detail(job_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    job = c.fetchone()
    conn.close()
    if not job:
        return redirect('/')
    return render_template('detail.html', job=job)


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/generate-ideas')
@rate_limit(max_calls=5, period=60)  # FIX: 5 appels max par minute par IP
def generate_ideas():
    import random
    ideas = [
        "Build a Telegram AI agent that replies automatically using Termux + Python",
        "Create a phone-only X growth bot (Termux script that likes & comments)",
        "Scrape trending TikTok sounds and auto-post Reels via Termux",
        "Make a lightweight AI content repurposer (YouTube → X threads)",
        "Develop a mobile solopreneur dashboard that runs entirely in Termux",
        "Automate Stripe payouts + invoice generation from phone",
        "Build a no-laptop dropshipping notifier (price tracker in Termux)",
        "Create an AI agent that finds micro-influencers on X and DMs them",
        "Phone-only lead gen bot for indie hackers (Scrapes IndieHackers + DM)",
        "Termux-based crypto arbitrage alert system (super light)",
    ]
    random.shuffle(ideas)
    return jsonify({"ideas": ideas[:4]})


# ── Admin dashboard ──────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required  # FIX: protégé par session, plus par clé dans l'URL
def admin():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = c.fetchall()
    conn.close()
    return render_template('admin.html', jobs=jobs)


@app.route('/delete/<int:job_id>', methods=['POST'])  # FIX: POST uniquement
@admin_required
def delete_job(job_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
