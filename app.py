from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Création DB SQLite
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

@app.route('/')
def index():
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = c.fetchall()
    conn.close()
    return render_template('index.html', jobs=jobs)

@app.route('/post', methods=['GET', 'POST'])
def post_job():
    if request.method == 'POST':
        title = request.form['title']
        company = request.form['company']
        description = request.form['description']
        niche = request.form['niche']
        budget = request.form['budget']
        contact = request.form['contact']
        conn = sqlite3.connect('jobs.db')
        c = conn.cursor()
        c.execute("INSERT INTO jobs (title, company, description, niche, budget, contact, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (title, company, description, niche, budget, contact, datetime.now().strftime("%d/%m/%Y")))
        conn.commit()
        conn.close()
        return redirect('/')
    return render_template('post.html')

@app.route('/job/<int:job_id>')
def job_detail(job_id):
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    job = c.fetchone()
    conn.close()
    return render_template('detail.html', job=job)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
