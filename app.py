from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import datetime, datetimedelta
import stripe
import os
import json

app = Flask(__name__)

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# DB
def init_db():
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY,
        title TEXT,
        company TEXT,
        description TEXT,
        niche TEXT,
        budget TEXT,
        contact TEXT,
        date TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# Ajoute cette fonction n'importe où dans app.py (après init_db par exemple)
def get_gigs_this_week():
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    one_week_ago = (datetime.now() - timedelta(days=7)).strftime("%d/%m/%Y")
    # Note: ça marche si la date est au format dd/mm/yyyy. Si tu veux plus précis, on peut changer plus tard.
    c.execute("SELECT COUNT(*) FROM jobs WHERE date >= ?", (one_week_ago,))
    count = c.fetchone()[0]
    conn.close()
    return count

@app.route('/')
def index():
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = c.fetchall()
    conn.close()
    weekly_count = get_gigs_this_week()
    return render_template('index.html', jobs=jobs, weekly_count=weekly_count)

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    # Récupère les données du formulaire
    title = request.form['title']
    company = request.form['company']
    description = request.form['description']
    niche = request.form['niche']
    budget = request.form['budget']
    contact = request.form['contact']

    # Crée la session Stripe ($29 one-time)
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Post a gig on PhoneOnlyGigs',
                        'description': 'Your gig will be live instantly after payment',
                    },
                    'unit_amount': 2900,  # 29.00 USD
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://phoneonlygigs.com/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://phoneonlygigs.com/post',
            metadata={
                'job_data': json.dumps({
                    'title': title,
                    'company': company,
                    'description': description,
                    'niche': niche,
                    'budget': budget,
                    'contact': contact
                })
            }
        )
        return redirect(session.url, code=303)
    except Exception as e:
        return f"Error: {str(e)}", 400

@app.route('/success')
def success():
    session_id = request.args.get('session_id')
    if not session_id:
        return redirect('/')

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == 'paid':
            job_data = json.loads(session.metadata['job_data'])

            conn = sqlite3.connect('jobs.db')
            c = conn.cursor()
            c.execute("""INSERT INTO jobs 
                         (title, company, description, niche, budget, contact, date) 
                         VALUES (?, ?, ?, ?, ?, ?, ?)""",
                      (job_data['title'], job_data['company'], job_data['description'],
                       job_data['niche'], job_data['budget'], job_data['contact'],
                       datetime.now().strftime("%d/%m/%Y")))
            conn.commit()
            conn.close()

            return render_template('success.html')
    except:
        pass

    return redirect('/')

@app.route('/post', methods=['GET'])
def post_job_get():
    return render_template('post.html')

@app.route('/job/<int:job_id>')
def job_detail(job_id):
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    job = c.fetchone()
    conn.close()
    return render_template('detail.html', job=job)

# ==================== AJOUTE ÇA À LA FIN DE app.py ====================

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/generate-ideas')
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
        "Termux-based crypto arbitrage alert system (super light)"
    ]
    random.shuffle(ideas)
    return jsonify({"ideas": ideas[:4]})

# ==================== ADMIN DASHBOARD ====================

@app.route('/admin')
def admin():
    admin_key = request.args.get('key')
    if admin_key != os.getenv('ADMIN_KEY'):
        return "<h1 class='text-center mt-5'>❌ Wrong key. You are not the owner.</h1>", 403

    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = c.fetchall()
    conn.close()

    return render_template('admin.html', jobs=jobs, admin_key=admin_key)

@app.route('/delete/<int:job_id>')
def delete_job(job_id):
    admin_key = request.args.get('key')
    if admin_key != os.getenv('ADMIN_KEY'):
        return "Unauthorized", 403

    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()
    return redirect(f'/admin?key={admin_key}')

# ========================================================

    if __name__ == '__main__':
       app.run(host='0.0.0.0', port=5000)
