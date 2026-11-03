"""Food planning, additive migrations and durable employee reminders."""
import calendar
import math
import statistics
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def local_day():
    try:
        return datetime.now(ZoneInfo('Asia/Qyzylorda')).date()
    except ZoneInfoNotFoundError:
        from datetime import timezone
        return datetime.now(timezone(timedelta(hours=5))).date()


def migrate(db):
    columns = {r[1] for r in db.execute('PRAGMA table_info(reports)')}
    if 'portions' not in columns:
        db.execute('ALTER TABLE reports ADD COLUMN portions INTEGER')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS dishes(id INTEGER PRIMARY KEY,
      report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
      name TEXT NOT NULL, prepared INTEGER NOT NULL, served INTEGER NOT NULL,
      leftover INTEGER NOT NULL, leftover_kg REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS report_requests(user_id INTEGER NOT NULL REFERENCES users(id),
      request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, report_id INTEGER NOT NULL REFERENCES reports(id),
      PRIMARY KEY(user_id,request_id));
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
      period TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL,
      read_at TEXT, resolved_at TEXT, UNIQUE(user_id,period));
    INSERT OR IGNORE INTO settings(key,value) VALUES ('deadline_day','5');
    ''')


def generate_reminders(db, today=None):
    today = today or local_day()
    # Each month's report is due on the configured day of the following month.
    last = today.replace(day=1) - timedelta(days=1)
    start, end = last.replace(day=1).isoformat(), last.isoformat()
    period = start[:7]
    deadline = int(db.execute("SELECT value FROM settings WHERE key='deadline_day'").fetchone()[0])
    due = today.replace(day=min(deadline, calendar.monthrange(today.year, today.month)[1]))
    stamp = datetime.now().astimezone().isoformat()
    # Late submissions can resolve older reminders, not only last month's one.
    db.execute('''UPDATE notifications SET resolved_at=CASE WHEN EXISTS (
      SELECT 1 FROM reports r JOIN users u ON u.org_id=r.org_id
      WHERE u.id=notifications.user_id AND substr(r.report_date,1,7)=notifications.period
      AND r.status IN ('submitted','in_review','accepted')) THEN COALESCE(resolved_at,?) ELSE NULL END''', (stamp,))
    for user in db.execute("SELECT u.id,u.org_id,o.name FROM users u JOIN organizations o ON o.id=u.org_id WHERE u.role='operator'").fetchall():
        sent = db.execute("SELECT 1 FROM reports WHERE org_id=? AND report_date BETWEEN ? AND ? AND status IN ('submitted','in_review','accepted') LIMIT 1", (user['org_id'], start, end)).fetchone()
        if sent:
            db.execute('UPDATE notifications SET resolved_at=COALESCE(resolved_at,?) WHERE user_id=? AND period=?', (stamp, user['id'], period))
        elif today >= due:
            db.execute('''INSERT OR IGNORE INTO notifications(user_id,period,title,message,created_at)
                VALUES (?,?,?,?,?)''', (user['id'], period, 'Есеп тапсыру мерзімі',
                f"{user['name']}: {period} айының есебі жіберілмеген. Мерзімі: {due.isoformat()}. Черновикті тексеруге жіберіңіз.", stamp))
            # A returned report reopens an existing reminder, without duplicate messages.
            db.execute('UPDATE notifications SET resolved_at=NULL WHERE user_id=? AND period=?', (user['id'], period))


def food_insights(reports, target, planning_reports=None):
    accepted = [r for r in reports if r['status'] == 'accepted']
    covered = [r for r in accepted if r.get('portions')]
    portions = sum(r['portions'] for r in covered)
    mass = sum(r['kg'] for r in covered)
    groups, days = {}, {}
    for report in accepted:
        if not report.get('dishes'):
            continue
        weekday = date.fromisoformat(report['report_date']).weekday()
        for dish in report.get('dishes', []):
            key = (report['org_id'], dish['name'].strip().casefold(), weekday)
            row = groups.setdefault(key, {'org_id': report['org_id'], 'org_name': report['org_name'], 'name': dish['name'], 'weekday': weekday, 'prepared': 0, 'served': 0, 'leftover': 0, 'kg': 0, 'dates': set(), 'excess_dates': set()})
            for field in ('prepared', 'served', 'leftover'):
                row[field] += dish[field]
            row['kg'] += dish['leftover_kg']
            row['dates'].add(report['report_date'])
            if dish['leftover'] or dish['leftover_kg']:
                row['excess_dates'].add(report['report_date'])
            # Aggregate duplicate meals/reports on the same day before planning.
            daily = days.setdefault((report['org_id'], key[1], report['report_date']), {'org_id': report['org_id'], 'org_name': report['org_name'], 'name': dish['name'], 'date': report['report_date'], 'prepared': 0, 'served': 0})
            daily['prepared'] += dish['prepared']
            daily['served'] += dish['served']
    excess = []
    for row in groups.values():
        row['days'], row['excess_days'] = len(row.pop('dates')), len(row.pop('excess_dates'))
        row['kg'] = round(row['kg'], 2)
        row['leftover_pct'] = round(row['leftover'] / row['prepared'] * 100, 1) if row['prepared'] else 0
        excess.append(row)
    excess.sort(key=lambda r: (-r['excess_days'], -r['kg']))
    if planning_reports is not None:
        days = {}
        for report in planning_reports:
            if report['status'] != 'accepted':
                continue
            for dish in report.get('dishes', []):
                key = (report['org_id'], dish['name'].strip().casefold(), report['report_date'])
                daily = days.setdefault(key, {'org_id': report['org_id'], 'org_name': report['org_name'], 'name': dish['name'], 'date': report['report_date'], 'prepared': 0, 'served': 0})
                daily['prepared'] += dish['prepared']
                daily['served'] += dish['served']
    candidates = {}
    cutoff = target - timedelta(days=56)
    for row in days.values():
        if cutoff <= date.fromisoformat(row['date']) < target:
            candidates.setdefault((row['org_id'], row['name'].casefold()), []).append(row)
    recommendations = []
    for history in candidates.values():
        history.sort(key=lambda r: r['date'], reverse=True)
        matching = [r for r in history if date.fromisoformat(r['date']).weekday() == target.weekday()]
        sample = matching[:8] if len(matching) >= 3 else history[:8]
        n = len(sample)
        median = statistics.median(r['served'] for r in sample)
        recommendations.append({'org_id': sample[0]['org_id'], 'org_name': sample[0]['org_name'], 'name': sample[0]['name'],
          'sample_days': n, 'same_weekday': len(matching) >= 3, 'median_served': median,
          'min_served': min(r['served'] for r in sample), 'max_served': max(r['served'] for r in sample),
          'mean_prepared': round(statistics.mean(r['prepared'] for r in sample), 1),
          'suggested': math.ceil(median * 1.05) if n >= 3 else None,
          'last_date': sample[0]['date']})
    recommendations.sort(key=lambda r: (r['org_name'], r['name']))
    return {'portions': portions, 'covered_kg': round(mass, 2), 'kg_per_100': round(mass / portions * 100, 2) if portions else None,
      'covered_reports': len(covered), 'accepted_reports': len(accepted), 'excess': excess, 'recommendations': recommendations,
      'target': target.isoformat(), 'method': 'Соңғы 56 күн: сол апта күнінің кемінде 3 күні, әйтпесе соңғы 8 күн. Сатылған порция медианасы × 1,05; жоғарыға дөңгелектеу. Кемінде 3 күн қажет.'}
