"""
db.py — Toute la logique base de données de PhoneOnlyGigs.

Règle : app.py ne touche jamais sqlite3 directement.
        Il appelle uniquement les fonctions de ce module.
"""

import sqlite3
from datetime import datetime, timedelta

DB_PATH = 'jobs.db'


# ── Connexion ─────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """Retourne une connexion avec row_factory → accès par nom (row['title'])."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Initialisation ────────────────────────────────────────────────────────────

def init_db() -> None:
    """Crée les tables si elles n'existent pas encore. Appelé au démarrage."""
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id          INTEGER PRIMARY KEY,
            title       TEXT    NOT NULL,
            company     TEXT    NOT NULL,
            description TEXT    NOT NULL,
            niche       TEXT    NOT NULL,
            budget      TEXT    NOT NULL,
            contact     TEXT    NOT NULL,
            date        TEXT    NOT NULL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS processed_sessions (
            session_id   TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
    ''')

    # Migration : ajout des colonnes featured si elles n'existent pas encore
    # (SQLite ne supporte pas ADD COLUMN IF NOT EXISTS avant 3.37)
    existing = {row[1] for row in c.execute("PRAGMA table_info(jobs)")}
    if 'featured' not in existing:
        c.execute("ALTER TABLE jobs ADD COLUMN featured INTEGER NOT NULL DEFAULT 0")
    if 'featured_until' not in existing:
        c.execute("ALTER TABLE jobs ADD COLUMN featured_until TEXT")

    conn.commit()
    conn.close()


# ── Lecture ───────────────────────────────────────────────────────────────────

def get_all_jobs() -> list[sqlite3.Row]:
    """Retourne tous les gigs, du plus récent au plus ancien (admin, pas de pagination)."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY id DESC")
    jobs = c.fetchall()
    conn.close()
    return jobs


def get_featured_jobs() -> list[sqlite3.Row]:
    """Retourne les gigs featured actifs (non expirés), du plus récent au plus ancien."""
    conn  = get_db()
    c     = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute(
        "SELECT * FROM jobs WHERE featured = 1 AND featured_until >= ? ORDER BY id DESC",
        (today,)
    )
    jobs = c.fetchall()
    conn.close()
    return jobs


def get_jobs_paginated(page: int, per_page: int) -> tuple[list[sqlite3.Row], int]:
    """
    Retourne (gigs_de_la_page, total_gigs) en excluant les featured actifs.
    page est 1-indexé.
    """
    conn   = get_db()
    c      = conn.cursor()
    today  = datetime.now().strftime('%Y-%m-%d')
    offset = (page - 1) * per_page

    # On exclut les gigs featured actifs — ils s'affichent en bloc séparé
    c.execute(
        "SELECT COUNT(*) FROM jobs WHERE NOT (featured = 1 AND featured_until >= ?)",
        (today,)
    )
    total = c.fetchone()[0]

    c.execute(
        """SELECT * FROM jobs
           WHERE NOT (featured = 1 AND featured_until >= ?)
           ORDER BY id DESC LIMIT ? OFFSET ?""",
        (today, per_page, offset)
    )
    jobs = c.fetchall()
    conn.close()
    return jobs, total


def get_job(job_id: int) -> sqlite3.Row | None:
    """Retourne un gig par son id, ou None s'il n'existe pas."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    job = c.fetchone()
    conn.close()
    return job


def get_gigs_this_week() -> int:
    """Retourne le nombre de gigs postés dans les 7 derniers jours."""
    conn = get_db()
    c = conn.cursor()
    one_week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(*) FROM jobs WHERE date >= ?", (one_week_ago,))
    count = c.fetchone()[0]
    conn.close()
    return count


# ── Écriture ──────────────────────────────────────────────────────────────────

def create_job(job_data: dict, featured: bool = False) -> int:
    """
    Insère un nouveau gig et retourne son id.
    job_data doit contenir : title, company, description, niche, budget, contact.
    Si featured=True, featured_until est fixé à aujourd'hui + 7 jours.
    """
    conn          = get_db()
    c             = conn.cursor()
    featured_int  = 1 if featured else 0
    featured_until = (
        (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        if featured else None
    )
    c.execute(
        """INSERT INTO jobs
               (title, company, description, niche, budget, contact, date, featured, featured_until)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_data['title'],
            job_data['company'],
            job_data['description'],
            job_data['niche'],
            job_data['budget'],
            job_data['contact'],
            datetime.now().strftime('%Y-%m-%d'),
            featured_int,
            featured_until,
        )
    )
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    return job_id


def toggle_featured(job_id: int, featured: bool) -> None:
    """Active ou désactive le featured d'un gig (usage admin)."""
    conn          = get_db()
    c             = conn.cursor()
    featured_int  = 1 if featured else 0
    featured_until = (
        (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        if featured else None
    )
    c.execute(
        "UPDATE jobs SET featured = ?, featured_until = ? WHERE id = ?",
        (featured_int, featured_until, job_id)
    )
    conn.commit()
    conn.close()


def delete_job(job_id: int) -> None:
    """Supprime un gig par son id."""
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()


# ── Idempotence Stripe ────────────────────────────────────────────────────────

def is_session_processed(session_id: str) -> bool:
    """Retourne True si cette session Stripe a déjà été traitée."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT session_id FROM processed_sessions WHERE session_id = ?",
        (session_id,)
    )
    exists = c.fetchone() is not None
    conn.close()
    return exists


def mark_session_processed(session_id: str) -> None:
    """Marque une session Stripe comme traitée pour éviter les doublons."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO processed_sessions (session_id, processed_at) VALUES (?, ?)",
        (session_id, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
