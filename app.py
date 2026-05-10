import json
import os
import re
import time
from collections import defaultdict
from functools import wraps

import stripe
from flask import (Flask, jsonify, redirect, render_template,
                   request, session, url_for)

import db
from db import (create_job, delete_job, get_all_jobs, get_featured_jobs,
                get_gigs_this_week, get_job, get_jobs_paginated,
                is_session_processed, mark_session_processed, toggle_featured)

# ── App ───────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-this-in-production')

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

db.init_db()


# ── Email ─────────────────────────────────────────────────────────────────────

def send_confirmation_email(to_email: str, job_data: dict, job_url: str) -> bool:
    """Envoie un email de confirmation via Resend. Retourne True si succès."""
    import urllib.request
    import urllib.error

    api_key = os.getenv('RESEND_API_KEY')
    if not api_key:
        print('[email] RESEND_API_KEY manquant — email non envoyé')
        return False

    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#0f0f0f;font-family:'Segoe UI',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f0f0f;padding:40px 20px;">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0"
                 style="background:#1a1a1a;border-radius:12px;overflow:hidden;border:1px solid #2a2a2a;">
            <tr>
              <td style="background:linear-gradient(135deg,#00c853,#1de9b6);padding:32px 40px;text-align:center;">
                <h1 style="margin:0;color:#fff;font-size:28px;">📱 PhoneOnlyGigs</h1>
                <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:15px;">
                  Your gig is live. The phone-only revolution is hiring.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:40px;">
                <p style="color:#e0e0e0;font-size:16px;margin:0 0 24px;">
                  Hey 👋 — your gig <strong style="color:#fff;">"{job_data['title']}"</strong>
                  is now live on PhoneOnlyGigs.
                </p>
                <table width="100%" cellpadding="0" cellspacing="0"
                       style="background:#111;border:1px solid #333;border-radius:10px;margin-bottom:32px;">
                  <tr>
                    <td style="padding:24px;">
                      <h2 style="margin:0 0 4px;color:#fff;font-size:20px;">{job_data['title']}</h2>
                      <p style="margin:0 0 16px;color:#888;font-size:14px;">
                        {job_data['company']} &nbsp;·&nbsp;
                        <span style="background:#1de9b615;color:#1de9b6;padding:2px 8px;border-radius:20px;font-size:12px;">
                          {job_data['niche']}
                        </span>
                      </p>
                      <p style="margin:0 0 16px;color:#ccc;font-size:14px;line-height:1.6;">
                        {job_data['description'][:200]}{'…' if len(job_data['description']) > 200 else ''}
                      </p>
                      <p style="margin:0;color:#aaa;font-size:13px;">
                        💰 Budget : <strong style="color:#fff;">{job_data['budget']}</strong>
                      </p>
                    </td>
                  </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
                  <tr>
                    <td align="center">
                      <a href="{job_url}"
                         style="display:inline-block;background:linear-gradient(135deg,#00c853,#1de9b6);
                                color:#fff;text-decoration:none;padding:14px 36px;border-radius:8px;
                                font-weight:700;font-size:15px;">
                        View your live gig →
                      </a>
                    </td>
                  </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0"
                       style="background:#0d2818;border:1px solid #1de9b630;border-radius:8px;margin-bottom:32px;">
                  <tr>
                    <td style="padding:20px 24px;">
                      <p style="margin:0 0 8px;color:#1de9b6;font-size:13px;font-weight:700;">ℹ️ Good to know</p>
                      <ul style="margin:0;padding-left:18px;color:#aaa;font-size:13px;line-height:1.8;">
                        <li>Your gig is active for <strong style="color:#e0e0e0;">30 days</strong></li>
                        <li>Freelancers will contact you directly via your listed contact</li>
                        <li>Need to edit or remove your gig? Reply to this email</li>
                      </ul>
                    </td>
                  </tr>
                </table>
                <p style="color:#666;font-size:13px;line-height:1.6;margin:0;">
                  Thanks for posting on PhoneOnlyGigs. Built from a phone, for people building from their phone. 🔥<br>
                  — The PhoneOnlyGigs team
                </p>
              </td>
            </tr>
            <tr>
              <td style="background:#111;padding:20px 40px;border-top:1px solid #222;text-align:center;">
                <p style="margin:0;color:#444;font-size:12px;">
                  PhoneOnlyGigs · You received this because you posted a gig ·
                  <a href="https://phoneonlygigs.com/privacy" style="color:#666;">Privacy</a>
                </p>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    payload = json.dumps({
        'from':    'PhoneOnlyGigs <noreply@phoneonlygigs.com>',
        'to':      [to_email],
        'subject': f'✅ Your gig "{job_data["title"]}" is live on PhoneOnlyGigs',
        'html':    html_body,
    }).encode()

    req = urllib.request.Request(
        'https://api.resend.com/emails',
        data=payload,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type':  'application/json',
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f'[email] Confirmation envoyée à {to_email} — status {resp.status}')
            return True
    except urllib.error.HTTPError as e:
        print(f'[email] Resend HTTP error {e.code}: {e.read().decode()}')
        return False
    except Exception as e:
        print(f'[email] Erreur inattendue: {e}')
        return False


# ── Rate limiter ──────────────────────────────────────────────────────────────

_rate_store: dict = defaultdict(list)


def rate_limit(max_calls: int, period: int):
    """Décorateur : max_calls requêtes par period secondes par IP."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip  = request.remote_addr
            now = time.time()
            _rate_store[ip] = [t for t in _rate_store[ip] if now - t < period]
            if len(_rate_store[ip]) >= max_calls:
                return jsonify({"error": "Too many requests. Try again later."}), 429
            _rate_store[ip].append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Auth admin ────────────────────────────────────────────────────────────────

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


# ── Validation formulaire ─────────────────────────────────────────────────────

ALLOWED_NICHES = {
    'AI Agent', 'Termux Script', 'Mobile Solopreneur',
    'Light Automation', 'Other phone-only',
}

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')


def validate_post_form(form) -> dict[str, str]:
    """Retourne un dict {champ: message_erreur} — vide si tout est OK."""
    errors: dict[str, str] = {}

    title = form.get('title', '').strip()
    if not title:
        errors['title'] = 'Title is required.'
    elif len(title) < 10:
        errors['title'] = 'Title must be at least 10 characters.'
    elif len(title) > 100:
        errors['title'] = 'Title must be 100 characters or less.'

    company = form.get('company', '').strip()
    if not company:
        errors['company'] = 'Handle / company is required.'
    elif len(company) > 60:
        errors['company'] = 'Handle / company must be 60 characters or less.'

    description = form.get('description', '').strip()
    if not description:
        errors['description'] = 'Description is required.'
    elif len(description) < 50:
        errors['description'] = (
            f'Description is too short ({len(description)}/50 chars min). '
            'Be specific so you get great applicants.'
        )
    elif len(description) > 2000:
        errors['description'] = f'Description must be 2 000 characters or less (currently {len(description)}).'

    niche = form.get('niche', '').strip()
    if niche not in ALLOWED_NICHES:
        errors['niche'] = 'Please select a valid niche.'

    budget = form.get('budget', '').strip()
    if not budget:
        errors['budget'] = 'Budget is required.'
    elif len(budget) > 80:
        errors['budget'] = 'Budget must be 80 characters or less.'

    contact = form.get('contact', '').strip()
    if not contact:
        errors['contact'] = 'Contact is required.'
    elif len(contact) > 120:
        errors['contact'] = 'Contact must be 120 characters or less.'

    raw_email = form.get('poster_email', '').strip().lower()
    if not raw_email:
        errors['poster_email'] = 'Your email is required to send the confirmation.'
    elif not EMAIL_RE.match(raw_email):
        errors['poster_email'] = 'Please enter a valid email address.'
    elif len(raw_email) > 254:
        errors['poster_email'] = 'Email address is too long.'

    return errors


# ── Routes publiques ──────────────────────────────────────────────────────────

PER_PAGE = 10  # gigs par page


@app.route('/')
def index():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    featured_jobs        = get_featured_jobs()
    jobs, total          = get_jobs_paginated(page, PER_PAGE)
    weekly_count         = get_gigs_this_week()

    import math
    total_pages = max(1, math.ceil(total / PER_PAGE))

    if page > total_pages:
        return redirect(url_for('index', page=total_pages))

    return render_template(
        'index.html',
        jobs=jobs,
        featured_jobs=featured_jobs,
        weekly_count=weekly_count,
        page=page,
        total_pages=total_pages,
        total_jobs=total,
    )


@app.route('/post', methods=['GET'])
def post_job_get():
    return render_template('post.html')


@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    errors = validate_post_form(request.form)
    if errors:
        return render_template('post.html', errors=errors, form=request.form), 422

    title        = request.form['title'].strip()
    company      = request.form['company'].strip()
    description  = request.form['description'].strip()
    niche        = request.form['niche'].strip()
    budget       = request.form['budget'].strip()
    contact      = request.form['contact'].strip()
    poster_email = request.form['poster_email'].strip().lower()

    # 3. Session Stripe — prix selon le type choisi
    is_featured = request.form.get('plan') == 'featured'
    unit_amount = 5900 if is_featured else 2900  # $59 featured / $29 standard
    plan_label  = 'Featured gig — top of the list for 7 days' if is_featured else 'Standard gig listing'

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'PhoneOnlyGigs — {plan_label}',
                        'description': 'Your gig will be live instantly after payment',
                    },
                    'unit_amount': unit_amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            customer_email=poster_email,
            success_url='https://phoneonlygigs.com/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://phoneonlygigs.com/post',
            metadata={
                'poster_email': poster_email,
                'featured': 'true' if is_featured else 'false',
                'job_data': json.dumps({
                    'title': title, 'company': company, 'description': description,
                    'niche': niche, 'budget': budget, 'contact': contact,
                })
            }
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return f"Error: {str(e)}", 400


@app.route('/success')
def success():
    if not request.args.get('session_id'):
        return redirect('/')
    return render_template('success.html')


@app.route('/job/<int:job_id>')
def job_detail(job_id):
    job = get_job(job_id)
    if not job:
        return render_template('404.html'), 404
    return render_template('detail.html', job=job)


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/generate-ideas')
@rate_limit(max_calls=5, period=60)
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


# ── Stripe Webhook ────────────────────────────────────────────────────────────

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload        = request.get_data()
    sig_header     = request.headers.get('Stripe-Signature')
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        print('[webhook] Invalid payload')
        return '', 400
    except stripe.error.SignatureVerificationError:
        print('[webhook] Invalid signature')
        return '', 400

    if event['type'] != 'checkout.session.completed':
        return '', 200

    stripe_session = event['data']['object']

    if stripe_session.get('payment_status') != 'paid':
        print(f"[webhook] Session {stripe_session['id']} not paid — skipping")
        return '', 200

    session_id = stripe_session['id']

    if is_session_processed(session_id):
        print(f"[webhook] Session {session_id} already processed — skipping")
        return '', 200

    try:
        job_data  = json.loads(stripe_session['metadata']['job_data'])
        is_featured = stripe_session['metadata'].get('featured') == 'true'
        job_id    = create_job(job_data, featured=is_featured)
        mark_session_processed(session_id)
        print(f"[webhook] Gig #{job_id} created (featured={is_featured}) for session {session_id} ✓")

        poster_email = stripe_session['metadata'].get('poster_email')
        if poster_email:
            job_url = f"https://phoneonlygigs.com/job/{job_id}"
            send_confirmation_email(poster_email, job_data, job_url)

    except Exception as e:
        print(f"[webhook] Error: {e}")
        return '', 500

    return '', 200


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():
    jobs = get_all_jobs()
    return render_template('admin.html', jobs=jobs)


@app.route('/delete/<int:job_id>', methods=['POST'])
@admin_required
def admin_delete_job(job_id):
    delete_job(job_id)
    return redirect(url_for('admin'))


@app.route('/feature/<int:job_id>', methods=['POST'])
@admin_required
def admin_toggle_featured(job_id):
    """Active ou désactive le featured d'un gig depuis l'admin."""
    action = request.form.get('action')  # 'enable' ou 'disable'
    toggle_featured(job_id, featured=(action == 'enable'))
    return redirect(url_for('admin'))


# ── Gestionnaires d'erreurs ───────────────────────────────────────────────────

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
