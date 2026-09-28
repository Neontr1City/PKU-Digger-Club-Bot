import json
import os
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from . import artwork, db, enrichment, music, poster
from . import service as s


def create_app(config=None):
    load_dotenv('.env.local')
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.getenv('SECRET_KEY'),
        ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD'),
        DATABASE=os.getenv('DATABASE', 'data/cricket.sqlite3'),
        OUTPUT_DIR=os.getenv('OUTPUT_DIR', 'output'),
        PUBLIC_BASE_URL=os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:5057').rstrip('/'),
        DEMO_MODE=os.getenv('DEMO_MODE') == '1',
        RESULT_FONT=os.getenv('RESULT_FONT', ''),
        ADMIN_EMAIL_ENABLED=os.getenv('ADMIN_EMAIL_ENABLED') == '1',
        QQ_SMTP_EMAIL=os.getenv('QQ_SMTP_EMAIL', ''),
        QQ_SMTP_AUTH_CODE=os.getenv('QQ_SMTP_AUTH_CODE', ''),
        ADMIN_EMAIL_TO=os.getenv('ADMIN_EMAIL_TO', ''),
        MAX_CONTENT_LENGTH=64 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(days=180),
    )
    if config:
        app.config.update(config)
    if not app.config['SECRET_KEY'] or not app.config['ADMIN_PASSWORD']:
        raise RuntimeError('请先运行 uv run python -m cricket init，生成本机私有配置。')
    app.config['SESSION_COOKIE_SECURE'] = app.config['PUBLIC_BASE_URL'].startswith('https://')
    password_hash = generate_password_hash(app.config['ADMIN_PASSWORD'])
    cover_signer = URLSafeSerializer(app.config['SECRET_KEY'], salt='album-artwork')
    db.initialize(app.config['DATABASE'])

    def database():
        if 'db' not in g:
            g.db = db.connect(app.config['DATABASE'])
        return g.db

    def is_admin():
        return session.get('admin_until', 0) > time.time()

    def admin_required(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            if not is_admin():
                return redirect(url_for('login')) if request.method == 'GET' else abort(403)
            return fn(*args, **kwargs)

        return decorated

    @app.teardown_appcontext
    def close_database(error=None):
        if 'db' in g:
            g.pop('db').close()

    @app.before_request
    def session_and_csrf():
        if request.endpoint in ('static', 'cover_image'):
            return
        session.permanent = True
        session.setdefault('csrf', secrets.token_hex(24))
        session.setdefault('voter', secrets.token_hex(24))
        if request.method == 'POST' and not secrets.compare_digest(
            session['csrf'], request.form.get('csrf', '')
        ):
            abort(400, '页面已过期，请刷新后重新提交。')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.endpoint not in ('static', 'cover_image'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def globals_():
        return dict(
            csrf=session.get('csrf'),
            admin=is_admin(),
            demo=app.config['DEMO_MODE'],
            today=s.utcnow().astimezone(s.SHANGHAI).date().isoformat(),
        )

    @app.template_filter('localtime')
    def localtime(value):
        return s.parse(value).astimezone(s.SHANGHAI).strftime('%m 月 %d 日 %H:%M')

    @app.template_filter('cover_url')
    def cover_url(source):
        return url_for('cover_image', token=cover_signer.dumps(source))

    @app.get('/artwork/<token>.png')
    def cover_image(token):
        # Only URLs signed when rendering our own metadata may trigger a download.
        try:
            source = cover_signer.loads(token)
        except BadSignature:
            abort(404)
        if not isinstance(source, str) or not artwork.allowed_url(source):
            abort(404)
        directory = Path(app.config['OUTPUT_DIR']) / 'artwork'
        if artwork.load_artwork(source, directory) is None:
            response = send_file(Path(app.static_folder) / 'cover-missing.svg')
            response.headers['Cache-Control'] = 'no-store'
            return response
        return send_file(artwork.cache_path(source, directory).resolve(), max_age=86400)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(error):
        return render_template('error.html', error=error), error.code

    @app.get('/')
    @app.get('/today')
    def today_page():
        conn = database()
        row = conn.execute(
            'SELECT day FROM rounds WHERE starts_at<=? ORDER BY starts_at DESC LIMIT 1',
            (s.stamp(s.utcnow()),),
        ).fetchone()
        return (
            display_round(row['day'])
            if row
            else render_template('round.html', round_=None, history=[])
        )

    def display_round(day):
        round_ = s.round_data(database(), day, session['voter'])
        if not round_:
            abort(404)
        history = (
            database()
            .execute(
                'SELECT day FROM rounds WHERE starts_at<=? ORDER BY day DESC LIMIT 8',
                (s.stamp(s.utcnow()),),
            )
            .fetchall()
        )
        return render_template('round.html', round_=round_, history=history)

    @app.get('/rounds/<day>')
    def round_page(day):
        return display_round(day)

    @app.post('/vote/<int:match_id>')
    def vote(match_id):
        row = (
            database()
            .execute(
                'SELECT r.day FROM rounds r JOIN matches m ON m.round_id=r.id WHERE m.id=?',
                (match_id,),
            )
            .fetchone()
        )
        if not row:
            abort(404)
        try:
            s.cast_vote(database(), match_id, session['voter'], request.form.get('choice'))
            flash(
                '已记下你的选择。截止前可以改票。'
                if request.form.get('choice') != 'clear'
                else '已撤回这一组的选择。',
                'success',
            )
        except ValueError as error:
            flash(str(error), 'error')
        return redirect(url_for('round_page', day=row['day']) + f'#match-{match_id}', 303)

    @app.route('/nominate', methods=['GET', 'POST'])
    def nominate():
        if request.method == 'POST':
            try:
                s.nominate(database(), request.form)
                return render_template('thanks.html')
            except ValueError as error:
                flash(str(error), 'error')
                return render_template(
                    'nominate.html',
                    form=request.form,
                    submission_id=request.form.get('submission_id'),
                ), 400
        return render_template('nominate.html', form={}, submission_id=secrets.token_hex(16))

    @app.route('/admin/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            if check_password_hash(password_hash, request.form.get('password', '')):
                session['admin_until'] = time.time() + 8 * 3600
                session['csrf'] = secrets.token_hex(24)
                return redirect(url_for('admin_page'), 303)
            flash('密码不正确。', 'error')
        return render_template('login.html')

    @app.post('/admin/logout')
    @admin_required
    def logout():
        session.pop('admin_until', None)
        return redirect(url_for('today_page'), 303)

    @app.get('/admin')
    @admin_required
    def admin_page():
        conn = database()
        s.close_due(conn)
        queue = [
            s.unpack(r)
            for r in conn.execute(
                "SELECT * FROM nominations WHERE status!='scheduled' ORDER BY created_at,id"
            )
        ]
        for item in queue:
            item['enrichment'] = enrichment.job(conn, item['id'])
        rounds = conn.execute('SELECT * FROM rounds ORDER BY day DESC LIMIT 30').fetchall()
        return render_template(
            'admin.html',
            queue=queue,
            rounds=rounds,
            settings=s.settings(conn),
            overrides=conn.execute('SELECT * FROM overrides ORDER BY day DESC').fetchall(),
            active_rounds=s.active_rounds(conn),
            checked_at=s.utcnow().astimezone(s.SHANGHAI).strftime('%H:%M:%S'),
        )

    @app.get('/admin/live-votes')
    @admin_required
    def live_votes():
        return render_template(
            '_live_votes.html',
            active_rounds=s.active_rounds(database()),
            checked_at=s.utcnow().astimezone(s.SHANGHAI).strftime('%H:%M:%S'),
        )

    @app.route('/admin/nomination/<int:nomination_id>', methods=['GET', 'POST'])
    @admin_required
    def review(nomination_id):
        row = (
            database().execute('SELECT * FROM nominations WHERE id=?', (nomination_id,)).fetchone()
        )
        if not row:
            abort(404)
        item = s.unpack(row)
        processing = enrichment.job(database(), nomination_id)
        if item['status'] == 'pending' and processing and processing['report']:
            for side, result in processing['report'].get('sides', {}).items():
                if result.get('track'):
                    item[side] = result['track']
        if request.method == 'POST':
            try:
                s.review(database(), nomination_id, request.form)
                flash('已确认，可以按序排期。', 'success')
                return redirect(url_for('admin_page'), 303)
            except ValueError as error:
                flash(str(error), 'error')
        return render_template(
            'review.html',
            item=item,
            form=request.form if request.method == 'POST' else {},
            original=json.loads(row['original']),
            processing=processing,
        )

    @app.post('/admin/nomination/<int:nomination_id>/resolve')
    @admin_required
    def resolve_nomination(nomination_id):
        try:
            enrichment.enqueue(database(), nomination_id)
            flash('已加入自动查找队列，后台 worker 将处理；稍后刷新查看结果。', 'success')
        except ValueError as error:
            flash(str(error), 'error')
        return redirect(url_for('review', nomination_id=nomination_id), 303)

    @app.post('/admin/nomination/<int:nomination_id>/status')
    @admin_required
    def status(nomination_id):
        state = request.form.get('status')
        if state not in ('pending', 'skipped'):
            abort(400)
        with database() as conn:
            conn.execute(
                "UPDATE nominations SET status=? WHERE id=? AND status!='scheduled'",
                (state, nomination_id),
            )
        return redirect(url_for('admin_page'), 303)

    @app.post('/admin/settings')
    @admin_required
    def save_settings():
        try:
            value = datetime.strptime(request.form.get('switch_time', ''), '%H:%M').strftime(
                '%H:%M'
            )
            cutoff = datetime.strptime(request.form.get('cutoff_time', ''), '%H:%M').strftime(
                '%H:%M'
            )
            if cutoff > value:
                raise ValueError('截止不能晚于次日发布，以免轮次重叠。')
            with database() as conn:
                conn.execute("UPDATE settings SET value=? WHERE key='switch_time'", (value,))
                conn.execute("UPDATE settings SET value=? WHERE key='cutoff_time'", (cutoff,))
                conn.execute(
                    "UPDATE settings SET value=? WHERE key='automatic'",
                    ('1' if request.form.get('automatic') else '0',),
                )
            flash('已保存。新时间只用于尚未创建的活动。', 'success')
        except ValueError:
            flash('请选择有效的发布时间和次日截止时间，截止不能晚于次日发布。', 'error')
        return redirect(url_for('admin_page'), 303)

    @app.post('/admin/schedule')
    @admin_required
    def schedule():
        try:
            day = datetime.strptime(request.form.get('day', ''), '%Y-%m-%d').date().isoformat()
            count = int(request.form.get('count', '1'))
            if not 0 <= count <= 20:
                raise ValueError('每天可设置 0—20 组。')
            if database().execute('SELECT 1 FROM rounds WHERE day=?', (day,)).fetchone():
                raise ValueError('该日期已创建投票，不能改写已发布曲目。')
            with database() as conn:
                conn.execute(
                    'INSERT INTO overrides VALUES (?,?) ON CONFLICT(day) DO UPDATE SET count=excluded.count',
                    (day, count),
                )
            if request.form.get('action') == 'create' and count:
                s.create_round(database(), day)
                flash('投票已创建；到开始时间后向群友开放。', 'success')
            else:
                flash('日期安排已保存。', 'success')
        except ValueError as error:
            flash(str(error), 'error')
        return redirect(url_for('admin_page'), 303)

    @app.get('/admin/music')
    @admin_required
    def search_music():
        query = request.args.get('q', '').strip()[:300]
        artist = request.args.get('artist', '').strip()[:160]
        provider = request.args.get('provider', 'itunes')
        country = request.args.get('country', 'cn')
        if country not in ('cn', 'us'):
            abort(400)
        items, error = [], ''
        if query:
            try:
                items = music.candidates(provider, query, country, artist)
            except Exception:
                error = '曲库暂时没有响应，请稍后再试，或使用下方官方来源手动核对。'
        return render_template(
            'music.html',
            items=items,
            query=query,
            artist=artist,
            provider=provider,
            country=country,
            error=error,
        )

    @app.get('/admin/round/<day>')
    @admin_required
    def round_admin(day):
        round_ = s.round_data(database(), day, admin=True)
        if not round_:
            abort(404)
        return render_template(
            'round_admin.html',
            round_=round_,
            message=s.nomination_message(round_, app.config['PUBLIC_BASE_URL']),
            congratulations=s.congratulations(round_['matches']) if round_['snapshot'] else '',
            dispatch=database().execute('SELECT * FROM dispatches WHERE day=?', (day,)).fetchone(),
        )

    @app.post('/admin/tick')
    @admin_required
    def run_tick():
        result = s.tick(database(), app.config['PUBLIC_BASE_URL'])
        flash(
            f'已结算 {result["closed"]} 轮。' + result.get('note', '') + ' 微信发送尚未接入。',
            'success',
        )
        return redirect(url_for('admin_page'), 303)

    @app.get('/rounds/<day>/result/<int:page>.png')
    def result_image(day, page):
        round_ = s.round_data(database(), day)
        if not round_ or not round_['snapshot']:
            abort(404)
        try:
            image = poster.render(
                round_, page, app.config['RESULT_FONT'], Path(app.config['OUTPUT_DIR']) / 'artwork'
            )
        except ValueError:
            abort(404)
        return send_file(image, mimetype='image/png', download_name=f'cricket-{day}-{page}.png')

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    return app
