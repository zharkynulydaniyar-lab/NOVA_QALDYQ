"""Telegram view of the existing student domain; no separate menus or orders."""
import mod_student
from common import APIError, local_day


def canteens(db):
    return [dict(r) for r in db.execute('SELECT * FROM organizations WHERE active=1 AND is_public=1 ORDER BY id')]


def preferences(db, user_id, data=None):
    db.execute('INSERT OR IGNORE INTO telegram_preferences(user_id) VALUES (?)',(user_id,))
    if data:
        if 'language' in data:
            if data['language'] not in ('ru','kk'):
                raise APIError('Выберите ru или kk.')
            db.execute('UPDATE telegram_preferences SET language=? WHERE user_id=?',(data['language'],user_id))
        if 'org_id' in data:
            org_id = int(data['org_id'])
            if org_id not in {r['id'] for r in canteens(db)}:
                raise APIError('Столовая недоступна.')
            db.execute('UPDATE telegram_preferences SET org_id=? WHERE user_id=?',(org_id,user_id))
    return dict(db.execute('SELECT * FROM telegram_preferences WHERE user_id=?',(user_id,)).fetchone())


def menu(db, org_id):
    if org_id not in {row['id'] for row in canteens(db)}:
        return []
    result=[]
    for day in db.execute("SELECT * FROM menu_days WHERE org_id=? AND day=? AND status='published'",(org_id,local_day().isoformat())).fetchall():
        view=mod_student.menu_view(db,day,public=True)
        for item in view['items']:
            result.append({'name_ru':item['name_ru'] or item['name'],'name_kk':item['name'],
                           'price':item['price_tiyn']/100,'remaining':item['remaining']})
    return result


def own_orders(db, user_id):
    return [{'id':r['id'],'total':r['total_tiyn']/100,'status':r['status']} for r in db.execute(
        'SELECT id,total_tiyn,status FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10',(user_id,))]
