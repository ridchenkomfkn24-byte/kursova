"""Вебплатформа «Словопростір»: користувачі, публікації та обговорення."""
import math
import os
import re
import secrets
import sqlite3
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
CATEGORIES = ('Технології', 'Культура', 'Саморозвиток', 'Подорожі', 'Суспільство')
COVERS = ('sage', 'peach', 'lavender', 'sand', 'sky')


def create_app(test_config=None):
    instance_path = ((test_config or {}).get('INSTANCE_PATH')
                     or os.environ.get('SLOVOPROSTIR_INSTANCE') or str(ROOT / 'instance'))
    app = Flask(__name__, instance_path=instance_path)
    Path(app.instance_path).mkdir(exist_ok=True)
    secret_file = Path(app.instance_path) / 'secret.key'
    if not secret_file.exists():
        secret_file.write_text(secrets.token_hex(32), encoding='utf-8')
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY') or secret_file.read_text(encoding='utf-8'),
        DATABASE=str(Path(app.instance_path) / 'platform.db'),
        MAX_CONTENT_LENGTH=1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )
    if test_config:
        app.config.update(test_config)

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'])
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys = ON')
        return g.db

    @app.teardown_appcontext
    def close_db(error=None):
        connection = g.pop('db', None)
        if connection:
            connection.close()

    @app.before_request
    def load_user_and_check_csrf():
        g.user = db().execute('SELECT * FROM users WHERE id = ?',
                              (session.get('user_id'),)).fetchone()
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        if request.method == 'POST':
            token = request.form.get('csrf_token', '')
            if not secrets.compare_digest(token, session['csrf_token']):
                abort(400, 'Форма застаріла. Онови сторінку та спробуй ще раз.')

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; base-uri 'self'; form-action 'self'; frame-ancestors 'self'")
        return response

    @app.context_processor
    def common_data():
        return dict(categories=CATEGORIES, covers=COVERS, current_user=g.get('user'))

    @app.template_filter('date_uk')
    def date_uk(value):
        months = ('січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
                  'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня')
        date = value[:10].split('-')
        return f'{int(date[2])} {months[int(date[1]) - 1]} {date[0]}'

    @app.template_filter('reading_time')
    def reading_time(value):
        return max(1, math.ceil(len(value.split()) / 180))

    @app.template_filter('plural_uk')
    def plural_uk(number, one, few, many):
        number = abs(int(number))
        if 11 <= number % 100 <= 14:
            return many
        if number % 10 == 1:
            return one
        if 2 <= number % 10 <= 4:
            return few
        return many

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                flash('Увійди, щоб скористатися цією можливістю.', 'info')
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped

    def get_article(article_id, owner_only=False):
        article = db().execute('''SELECT a.*, u.name AS author_name, u.bio AS author_bio
            FROM articles a JOIN users u ON u.id = a.author_id WHERE a.id = ?''',
                               (article_id,)).fetchone()
        if not article:
            abort(404)
        is_owner = g.user and g.user['id'] == article['author_id']
        if owner_only and not is_owner:
            abort(403)
        if article['status'] != 'published' and not is_owner:
            abort(404)
        return article

    @app.route('/')
    def index():
        query = request.args.get('q', '').strip()[:150]
        category = request.args.get('category', '')
        sort = request.args.get('sort', 'new')
        if category not in CATEGORIES:
            category = ''
        conditions, params = ["a.status = 'published'"], []
        if query:
            # Python casefold забезпечує пошук українською незалежно від регістру.
            conditions.append('(CASEFOLD(a.title || a.summary || a.content || u.name) LIKE ?)')
            params.append('%' + query.casefold() + '%')
        if category:
            conditions.append('a.category = ?')
            params.append(category)
        db().create_function('CASEFOLD', 1, lambda s: s.casefold())
        where = ' AND '.join(conditions)
        total = db().execute(f'''SELECT COUNT(*) FROM articles a
            JOIN users u ON u.id = a.author_id WHERE {where}''', params).fetchone()[0]
        pages = max(1, math.ceil(total / 6))
        page = min(max(request.args.get('page', 1, type=int), 1), pages)
        order = 'a.created_at DESC, a.id DESC' if sort != 'old' else 'a.created_at, a.id'
        articles = db().execute(f'''SELECT a.*, u.name AS author_name,
            (SELECT COUNT(*) FROM comments c WHERE c.article_id = a.id) AS comments_count
            FROM articles a JOIN users u ON u.id = a.author_id WHERE {where}
            ORDER BY {order} LIMIT 6 OFFSET ?''', params + [(page - 1) * 6]).fetchall()
        stats = dict(articles=db().execute("SELECT COUNT(*) FROM articles WHERE status='published'").fetchone()[0],
                     authors=db().execute("SELECT COUNT(DISTINCT author_id) FROM articles WHERE status='published'").fetchone()[0])
        return render_template('index.html', articles=articles, query=query, category=category,
                               sort=sort, total=total, page=page, pages=pages, stats=stats)

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if g.user:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            error = None
            if not 2 <= len(name) <= 60:
                error = 'Ім’я має містити від 2 до 60 символів.'
            elif len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                error = 'Вкажи коректну електронну адресу.'
            elif not 8 <= len(password) <= 128:
                error = 'Пароль має містити від 8 до 128 символів.'
            elif password != request.form.get('confirm_password'):
                error = 'Паролі не збігаються.'
            if error:
                flash(error, 'error')
            else:
                try:
                    cur = db().execute('INSERT INTO users(name,email,password_hash) VALUES(?,?,?)',
                                       (name, email, generate_password_hash(password)))
                    db().commit()
                    session.clear()
                    session['user_id'] = cur.lastrowid
                    session.permanent = True
                    flash('Раді бачити тебе у Словопросторі!', 'success')
                    return redirect(url_for('dashboard'))
                except sqlite3.IntegrityError:
                    flash('Ця електронна адреса вже зареєстрована.', 'error')
        return render_template('auth.html', mode='register')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if g.user:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            user = db().execute('SELECT * FROM users WHERE email = ?',
                                (request.form.get('email', '').strip().lower(),)).fetchone()
            password = request.form.get('password', '')
            if user and len(password) <= 128 and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session.permanent = True
                return redirect(url_for('dashboard'))
            flash('Неправильна електронна адреса або пароль.', 'error')
        return render_template('auth.html', mode='login')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    @app.get('/cabinet')
    @login_required
    def dashboard():
        articles = db().execute('''SELECT * FROM articles WHERE author_id = ?
            ORDER BY updated_at DESC, id DESC''', (g.user['id'],)).fetchall()
        return render_template('dashboard.html', articles=articles)

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            bio = request.form.get('bio', '').strip()
            if 2 <= len(name) <= 60 and len(bio) <= 300:
                db().execute('UPDATE users SET name=?, bio=? WHERE id=?', (name, bio, g.user['id']))
                db().commit()
                flash('Профіль оновлено.', 'success')
                return redirect(url_for('dashboard'))
            flash('Перевір ім’я (2–60 символів) та опис (до 300 символів).', 'error')
        return render_template('profile.html')

    @app.route('/articles/new', methods=['GET', 'POST'])
    @app.route('/articles/<int:article_id>/edit', methods=['GET', 'POST'])
    @login_required
    def editor(article_id=None):
        article = get_article(article_id, owner_only=True) if article_id else None
        data = dict(article) if article else {}
        if request.method == 'POST':
            data = {key: request.form.get(key, '').strip()
                    for key in ('title', 'summary', 'content', 'category', 'cover', 'status')}
            error = None
            if not 5 <= len(data['title']) <= 140:
                error = 'Заголовок має містити від 5 до 140 символів.'
            elif not 15 <= len(data['summary']) <= 300:
                error = 'Короткий опис має містити від 15 до 300 символів.'
            elif not 50 <= len(data['content']) <= 50000:
                error = 'Текст статті має містити від 50 до 50 000 символів.'
            elif data['category'] not in CATEGORIES or data['cover'] not in COVERS:
                error = 'Обери категорію та обкладинку зі списку.'
            elif data['status'] not in ('draft', 'published'):
                error = 'Обери коректний стан статті.'
            if error:
                flash(error, 'error')
            else:
                values = tuple(data[key] for key in ('title', 'summary', 'content', 'category', 'cover', 'status'))
                if article:
                    db().execute('''UPDATE articles SET title=?, summary=?, content=?, category=?,
                        cover=?, status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?''', values + (article_id,))
                else:
                    cur = db().execute('''INSERT INTO articles
                        (title,summary,content,category,cover,status,author_id) VALUES(?,?,?,?,?,?,?)''',
                                       values + (g.user['id'],))
                    article_id = cur.lastrowid
                db().commit()
                flash('Статтю опубліковано.' if data['status'] == 'published' else 'Чернетку збережено.', 'success')
                return redirect(url_for('article_detail', article_id=article_id))
        return render_template('editor.html', article=article, data=data)

    @app.get('/articles/<int:article_id>')
    def article_detail(article_id):
        article = get_article(article_id)
        comments = db().execute('''SELECT c.*, u.name FROM comments c
            JOIN users u ON u.id=c.user_id WHERE article_id=? ORDER BY c.id DESC''', (article_id,)).fetchall()
        bookmarked = g.user and db().execute('SELECT 1 FROM bookmarks WHERE user_id=? AND article_id=?',
                                              (g.user['id'], article_id)).fetchone()
        related = db().execute('''SELECT a.*,u.name AS author_name FROM articles a
            JOIN users u ON u.id=a.author_id WHERE a.status='published' AND a.id!=?
            AND a.category=? ORDER BY a.id DESC LIMIT 2''', (article_id, article['category'])).fetchall()
        return render_template('article.html', article=article, comments=comments,
                               bookmarked=bool(bookmarked), related=related)

    @app.post('/articles/<int:article_id>/delete')
    @login_required
    def delete_article(article_id):
        get_article(article_id, owner_only=True)
        db().execute('DELETE FROM articles WHERE id=?', (article_id,))
        db().commit()
        flash('Статтю видалено.', 'success')
        return redirect(url_for('dashboard'))

    @app.post('/articles/<int:article_id>/comments')
    @login_required
    def add_comment(article_id):
        article = get_article(article_id)
        if article['status'] != 'published':
            abort(400, 'Коментарі доступні після публікації статті.')
        content = request.form.get('content', '').strip()
        if not 2 <= len(content) <= 2000:
            flash('Коментар має містити від 2 до 2000 символів.', 'error')
        else:
            db().execute('INSERT INTO comments(article_id,user_id,content) VALUES(?,?,?)',
                         (article_id, g.user['id'], content))
            db().commit()
            flash('Коментар додано.', 'success')
        return redirect(url_for('article_detail', article_id=article_id) + '#comments')

    @app.post('/comments/<int:comment_id>/delete')
    @login_required
    def delete_comment(comment_id):
        comment = db().execute('SELECT * FROM comments WHERE id=?', (comment_id,)).fetchone()
        if not comment:
            abort(404)
        if comment['user_id'] != g.user['id']:
            abort(403)
        db().execute('DELETE FROM comments WHERE id=?', (comment_id,))
        db().commit()
        return redirect(url_for('article_detail', article_id=comment['article_id']) + '#comments')

    @app.post('/articles/<int:article_id>/bookmark')
    @login_required
    def bookmark(article_id):
        article = get_article(article_id)
        if article['status'] != 'published':
            abort(400)
        params = (g.user['id'], article_id)
        if db().execute('SELECT 1 FROM bookmarks WHERE user_id=? AND article_id=?', params).fetchone():
            db().execute('DELETE FROM bookmarks WHERE user_id=? AND article_id=?', params)
            flash('Статтю прибрано зі збережених.', 'info')
        else:
            db().execute('INSERT INTO bookmarks(user_id,article_id) VALUES(?,?)', params)
            flash('Статтю збережено для читання.', 'success')
        db().commit()
        return redirect(url_for('article_detail', article_id=article_id))

    @app.get('/saved')
    @login_required
    def saved():
        articles = db().execute('''SELECT a.*, u.name AS author_name FROM bookmarks b
            JOIN articles a ON a.id=b.article_id JOIN users u ON u.id=a.author_id
            WHERE b.user_id=? AND a.status='published' ORDER BY a.id DESC''', (g.user['id'],)).fetchall()
        return render_template('saved.html', articles=articles)

    @app.get('/authors/<int:author_id>')
    def author_blog(author_id):
        author = db().execute('SELECT id, name, bio, created_at FROM users WHERE id=?',
                              (author_id,)).fetchone()
        if not author:
            abort(404)
        total = db().execute("SELECT COUNT(*) FROM articles WHERE author_id=? AND status='published'",
                             (author_id,)).fetchone()[0]
        pages = max(1, math.ceil(total / 6))
        page = min(max(request.args.get('page', 1, type=int), 1), pages)
        articles = db().execute('''SELECT a.*, u.name AS author_name FROM articles a
            JOIN users u ON u.id=a.author_id WHERE a.author_id=? AND a.status='published'
            ORDER BY a.created_at DESC, a.id DESC LIMIT 6 OFFSET ?''',
                               (author_id, (page - 1) * 6)).fetchall()
        return render_template('author.html', author=author, articles=articles,
                               total=total, page=page, pages=pages)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(error):
        return render_template('error.html', code=error.code,
                               message=error.description if error.code == 400 else None), error.code

    with app.app_context():
        db().executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        if not app.config.get('TESTING') and not db().execute('SELECT 1 FROM users LIMIT 1').fetchone():
            from seed import seed_database
            seed_database(db())
    return app


if __name__ == '__main__':
    import sys
    application = create_app()
    if '--open-browser' in sys.argv:
        import threading
        import webbrowser

        def open_browser():
            paths = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')),
                     Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')),
                     Path(os.environ.get('LOCALAPPDATA', ''))]
            chrome = next((path / 'Google/Chrome/Application/chrome.exe' for path in paths
                           if (path / 'Google/Chrome/Application/chrome.exe').is_file()), None)
            browser = webbrowser.BackgroundBrowser(str(chrome)) if chrome else webbrowser
            browser.open('http://127.0.0.1:5000')

        timer = threading.Timer(1.5, open_browser)
        timer.daemon = True
        timer.start()
    application.run(host='127.0.0.1', port=5000, debug=False)
