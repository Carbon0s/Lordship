import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'lordship_super_secret_key_2026')

# =======================
# ПОДКЛЮЧЕНИЕ К POSTGRESQL (AIVEN)
# =======================
RAW_DB_URL = os.environ.get(
    'DATABASE_URL', 
    'postgres://avnadmin:AVNS_ui8VBMYvcbFDjIrZ8ja@lmbank-carbon0sik.g.aivencloud.com:11779/defaultdb?sslmode=require'
)

# SQLAlchemy требует префикс postgresql:// вместо postgres://
if RAW_DB_URL.startswith("postgres://"):
    RAW_DB_URL = RAW_DB_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = RAW_DB_URL

# Оптимизация подключений для предотвращения превышения лимитов и фризов
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_size": 3,
    "max_overflow": 2,
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# =======================
# КОНСТАНТЫ И НАСТРОЙКИ
# =======================
RANKS_EXP = {
    "Стажер": 0, "Рядовой": 5, "Ефрейтор": 10, "Младший Сержант": 15,
    "Сержант": 20, "Старший Сержант": 30, "Старшина": 40, "Прапорщик": 55,
    "Старший Прапорщик": 65, "Младший Лейтенант": 75, "Лейтенант": 85,
    "Старший Лейтенант": 90, "Капитан": 100, "Майор": 150, "Подполковник": 200,
    "Полковник": 300, "Генерал Лейтенант": 350, "Генерал Майор": 400,
    "Генерал Полковник": 500, "Генерал Lordship": 700
}

SPECIAL_RANKS = ["Заместитель Начальника", "Начальник", "Заместитель Ген.Начальника", "Ген.Начальник", "владелец"]
ADMIN_LEVELS = ["Нет", "Младший Модератор", "Модератор", "Администратор", "Специальный Администратор"]

DEPARTMENTS = {
    "Штурмовики": ["Младший штурмовик", "Штурмовик", "Старший Штурмовик", "Управляющий группой", "Начальник Штурмовиков"],
    "Разведка": ["Младший разведчик", "Разведчик", "Старший Разведчик", "Управляющий группой", "Начальник разведчиков"],
    "Моб.Группа": ["Младший оперативник", "Оперативник", "Старший Оперативник", "Управляющий группой", "Начальник моб. группы"],
    "ОС": ["Младший сотрудник", "Сотрудник ОС", "Старший Сотрудник", "Управляющий ОС", "Начальник ОС"]
}

ALL_ROLES_LIST = ADMIN_LEVELS[1:-1] + list(RANKS_EXP.keys()) + SPECIAL_RANKS

RANK_WEIGHTS = {
    "Стажер": 1, "Рядовой": 2, "Ефрейтор": 3, "Младший Сержант": 4,
    "Сержант": 5, "Старший Сержант": 6, "Старшина": 7, "Прапорщик": 8,
    "Старший Прапорщик": 9, "Младший Лейтенант": 10, "Лейтенант": 11,
    "Старший Лейтенант": 12, "Капитан": 13, "Майор": 14, "Подполковник": 15,
    "Полковник": 16, "Генерал Лейтенант": 17, "Генерал Майор": 18,
    "Генерал Полковник": 19, "Генерал Lordship": 20,
    "Заместитель Начальника": 21, "Начальник": 22,
    "Заместитель Ген.Начальника": 23, "Ген.Начальник": 24, "владелец": 25
}

ADMIN_WEIGHTS = {
    "Нет": 0,
    "Младший Модератор": 10,
    "Модератор": 20,
    "Администратор": 30,
    "Специальный Администратор": 100
}

# =======================
# МОДЕЛИ БАЗЫ ДАННЫХ
# =======================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    age = db.Column(db.Integer, default=18)
    exp = db.Column(db.Integer, default=0)
    rank = db.Column(db.String(50), default="Стажер")
    admin_level = db.Column(db.String(50), default="Нет")
    department = db.Column(db.String(50), default="Нет")
    dept_rank = db.Column(db.String(50), default="Нет")
    tasks_completed = db.Column(db.Integer, default=0)
    join_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    is_banned = db.Column(db.Boolean, default=False)
    ban_until = db.Column(db.DateTime, nullable=True)
    is_muted = db.Column(db.Boolean, default=False)
    mute_until = db.Column(db.DateTime, nullable=True)
    warns_count = db.Column(db.Integer, default=0)

    warn_reset_flag = db.Column(db.Boolean, default=False)
    warn_reset_time = db.Column(db.DateTime, nullable=True)

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    app_type = db.Column(db.String(50))
    target = db.Column(db.String(100))
    proof_url = db.Column(db.Text)
    status = db.Column(db.String(20), default="Ожидает")
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('applications', lazy=True))

class HistoryLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('history', lazy=True))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String(50))
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    author = db.relationship('User', backref=db.backref('messages', lazy=True))

class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    author = db.relationship('User', backref=db.backref('news_posts', lazy=True))

class RolePermission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(100), unique=True, nullable=False)
    can_view_apps = db.Column(db.Boolean, default=False)
    can_approve_apps = db.Column(db.Boolean, default=False)
    can_mute = db.Column(db.Boolean, default=False)
    can_ban = db.Column(db.Boolean, default=False)
    can_warn = db.Column(db.Boolean, default=False)
    can_force_action = db.Column(db.Boolean, default=False)
    can_post_news = db.Column(db.Boolean, default=False)
    can_delete_all_news = db.Column(db.Boolean, default=False)
    can_view_history = db.Column(db.Boolean, default=False)

class UserPermissionOverride(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    can_view_apps = db.Column(db.Boolean, default=False)
    can_approve_apps = db.Column(db.Boolean, default=False)
    can_mute = db.Column(db.Boolean, default=False)
    can_ban = db.Column(db.Boolean, default=False)
    can_warn = db.Column(db.Boolean, default=False)
    can_force_action = db.Column(db.Boolean, default=False)
    can_post_news = db.Column(db.Boolean, default=False)
    can_delete_all_news = db.Column(db.Boolean, default=False)
    can_view_history = db.Column(db.Boolean, default=False)
    user = db.relationship('User', backref=db.backref('perm_override', uselist=False))

# =======================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =======================
def get_current_user():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user and user.warn_reset_flag:
            flash("🚨 ВНИМАНИЕ: Ваш аккаунт был сброшен (звание, EXP, отдел) из-за достижения 3 предупреждений (варнов)!")
            user.warn_reset_flag = False
            db.session.commit()
        return user
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def check_perm(user, perm_name):
    if not user: return False
    if user.admin_level == "Специальный Администратор": return True
    
    if user.is_banned:
        if user.ban_until and datetime.utcnow() > user.ban_until:
            user.is_banned = False
            user.ban_until = None
            db.session.commit()
        else:
            return False

    override = UserPermissionOverride.query.filter_by(user_id=user.id).first()
    if override and getattr(override, perm_name, False):
        return True

    roles_to_check = [user.admin_level, user.rank, user.dept_rank]
    perms = RolePermission.query.filter(RolePermission.role_name.in_(roles_to_check)).all()
    for p in perms:
        if getattr(p, perm_name, False):
            return True
    return False

def can_sanction_target(admin_user, target_user):
    if admin_user.id == target_user.id:
        return False, "Запрещено применять дисциплинарные меры к самому себе!"
    
    if admin_user.admin_level == "Специальный Администратор":
        return True, ""
        
    admin_adm_w = ADMIN_WEIGHTS.get(admin_user.admin_level, 0)
    target_adm_w = ADMIN_WEIGHTS.get(target_user.admin_level, 0)
    
    if admin_adm_w < target_adm_w:
        return False, "Вы не можете применять санкции к администратору высшего уровня!"
    elif admin_adm_w == target_adm_w and admin_adm_w > 0:
        return False, "Вы не можете применять санкции к равного по уровню администратору!"
        
    admin_rnk_w = RANK_WEIGHTS.get(admin_user.rank, 0)
    target_rnk_w = RANK_WEIGHTS.get(target_user.rank, 0)
    
    if admin_adm_w == 0 and target_adm_w == 0:
        if admin_rnk_w <= target_rnk_w:
            return False, "Вы не можете применять санкции к бойцу равного или старшего звания!"
            
    return True, ""

def is_user_banned(user):
    if not user or not user.is_banned: return False
    if user.ban_until and datetime.utcnow() > user.ban_until:
        user.is_banned = False
        user.ban_until = None
        db.session.commit()
        return False
    return True

def is_user_muted(user):
    if not user or not user.is_muted: return False
    if user.mute_until and datetime.utcnow() > user.mute_until:
        user.is_muted = False
        user.mute_until = None
        db.session.commit()
        return False
    return True

def log_history(user_id, action):
    log = HistoryLog(user_id=user_id, action=action)
    db.session.add(log)
    db.session.commit()

def recalculate_rank(user):
    if user.rank in SPECIAL_RANKS: return
    best_rank = "Стажер"
    for r, e in RANKS_EXP.items():
        if user.exp >= e: best_rank = r
    if user.rank != best_rank:
        log_history(user.id, f"Звание изменено с {user.rank} на {best_rank} (EXP: {user.exp})")
        user.rank = best_rank
        db.session.commit()

def init_permissions():
    for r_name in ALL_ROLES_LIST:
        existing = RolePermission.query.filter_by(role_name=r_name).first()
        if not existing:
            can_v = r_name in ["Младший Модератор", "Модератор", "Администратор"]
            can_a = r_name in ["Модератор", "Администратор"]
            can_m = r_name in ["Младший Модератор", "Модератор", "Администратор"]
            can_b = r_name in ["Администратор"]
            can_w = r_name in ["Модератор", "Администратор"]
            can_f = r_name in ["Администратор"]
            can_p = r_name in ["Администратор", "Модератор"]
            can_da = r_name in ["Администратор"]
            can_vh = r_name in ["Младший Модератор", "Модератор", "Администратор"]
            
            p = RolePermission(
                role_name=r_name,
                can_view_apps=can_v,
                can_approve_apps=can_a,
                can_mute=can_m,
                can_ban=can_b,
                can_warn=can_w,
                can_force_action=can_f,
                can_post_news=can_p,
                can_delete_all_news=can_da,
                can_view_history=can_vh
            )
            db.session.add(p)
    db.session.commit()

def get_epaulette_svg(rank):
    w, h = 85, 34
    bg_color = "rgba(10, 20, 40, 0.9)"
    border_color = "rgba(0, 240, 255, 0.4)"
    accent_color = "#00f0ff"
    
    inner_svg = ""
    cy = 17
    
    def get_star(cx, cy, radius=5, color="#ffd700"):
        return f'<polygon points="{cx},{cy-radius} {cx+1.5},{cy-1.5} {cx+radius},{cy-1.5} {cx+2.5},{cy+1} {cx+3.5},{cy+radius} {cx},{cy+2.5} {cx-3.5},{cy+radius} {cx-2.5},{cy+1} {cx-radius},{cy-1.5} {cx-1.5},{cy-1.5}" fill="{color}"/>'

    if rank in ["Стажер", "Рядовой"]:
        inner_svg = f'<rect x="12" y="15" width="61" height="4" rx="2" fill="none" stroke="rgba(255,255,255,0.2)" stroke-dasharray="3,3"/>'
    elif rank == "Ефрейтор":
        inner_svg = f'<line x1="42.5" y1="8" x2="42.5" y2="26" stroke="{accent_color}" stroke-width="4" stroke-linecap="round"/>'
    elif rank == "Младший Сержант":
        inner_svg = f'<line x1="34" y1="8" x2="34" y2="26" stroke="{accent_color}" stroke-width="3.5" stroke-linecap="round"/><line x1="51" y1="8" x2="51" y2="26" stroke="{accent_color}" stroke-width="3.5" stroke-linecap="round"/>'
    elif rank == "Сержант":
        inner_svg = f'<line x1="26" y1="8" x2="26" y2="26" stroke="{accent_color}" stroke-width="3.5" stroke-linecap="round"/><line x1="42.5" y1="8" x2="42.5" y2="26" stroke="{accent_color}" stroke-width="3.5" stroke-linecap="round"/><line x1="59" y1="8" x2="59" y2="26" stroke="{accent_color}" stroke-width="3.5" stroke-linecap="round"/>'
    elif rank == "Старший Сержант":
        inner_svg = f'<line x1="18" y1="17" x2="67" y2="17" stroke="{accent_color}" stroke-width="5.5" stroke-linecap="round"/>'
    elif rank == "Старшина":
        inner_svg = f'<line x1="18" y1="21" x2="67" y2="21" stroke="{accent_color}" stroke-width="4.5" stroke-linecap="round"/><path d="M 25 12 L 42.5 6 L 60 12" fill="none" stroke="{accent_color}" stroke-width="3.5"/>'
    elif rank in ["Прапорщик", "Старший Прапорщик"]:
        cx_list = [30, 55] if rank == "Прапорщик" else [20, 42.5, 65]
        for cx in cx_list:
            inner_svg += get_star(cx, cy, 5.5, "#00f0ff")
    elif rank in ["Младший Лейтенант", "Лейтенант", "Старший Лейтенант", "Капитан"]:
        inner_svg += f'<line x1="12" y1="17" x2="73" y2="17" stroke="rgba(255,215,0,0.6)" stroke-width="2.5"/>'
        stars = 1 if rank == "Младший Лейтенант" else (2 if rank == "Лейтенант" else (3 if rank == "Старший Лейтенант" else 4))
        cx_list = [42.5] if stars == 1 else ([30, 55] if stars == 2 else ([20, 42.5, 65] if stars == 3 else [16, 33, 51, 68]))
        for cx in cx_list:
            inner_svg += get_star(cx, cy, 5, "#ffd700")
    elif rank in ["Майор", "Подполковник", "Полковник"]:
        inner_svg += f'<line x1="12" y1="11" x2="73" y2="11" stroke="rgba(255,215,0,0.8)" stroke-width="2"/><line x1="12" y1="23" x2="73" y2="23" stroke="rgba(255,215,0,0.8)" stroke-width="2"/>'
        stars = 1 if rank == "Майор" else (2 if rank == "Подполковник" else 3)
        cx_list = [42.5] if stars == 1 else ([30, 55] if stars == 2 else [20, 42.5, 65])
        for cx in cx_list:
            inner_svg += get_star(cx, cy, 5.5, "#ffd700")
    elif rank in ["Генерал Лейтенант", "Генерал Майор", "Генерал Полковник", "Генерал Lordship"]:
        accent_color = "#b785ff"
        border_color = "rgba(183, 133, 255, 0.7)"
        inner_svg += f'<rect x="6" y="6" width="73" height="22" rx="4" fill="none" stroke="{accent_color}" stroke-width="1.5" stroke-dasharray="4,2"/>'
        stars = 1 if rank == "Генерал Майор" else (2 if rank == "Генерал Лейтенант" else (3 if rank == "Генерал Полковник" else 4))
        cx_list = [42.5] if stars == 1 else ([30, 55] if stars == 2 else ([20, 42.5, 65] if stars == 3 else [16, 33, 51, 68]))
        for cx in cx_list:
            inner_svg += get_star(cx, cy, 6, "#b785ff")
    else:
        accent_color = "#ff0055"
        border_color = "rgba(255, 0, 85, 0.9)"
        inner_svg = f'''
        <path d="M 12 17 Q 42.5 5 73 17 Q 42.5 29 12 17 Z" fill="rgba(255,0,85,0.25)" stroke="#ff0055" stroke-width="1.5"/>
        {get_star(42.5, 17, 6.5, "#ffd700")}
        <circle cx="20" cy="17" r="3" fill="#ff0055"/>
        <circle cx="65" cy="17" r="3" fill="#ff0055"/>
        '''

    svg = f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="vertical-align: middle; filter: drop-shadow(0 0 6px {border_color});"><rect x="2" y="2" width="{w-4}" height="{h-4}" rx="6" fill="{bg_color}" stroke="{border_color}" stroke-width="2"/>{inner_svg}</svg>'
    return svg

# =======================
# ШАБЛОНЫ И МАРШРУТЫ
# =======================
BASE_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Lordship Command Center</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #00f0ff;
            --primary-glow: rgba(0, 240, 255, 0.4);
            --secondary: #7000ff;
            --bg-glass: rgba(13, 17, 28, 0.92);
            --border-glass: rgba(255, 255, 255, 0.1);
            --text-main: #e2e8f0;
            --danger: #ff0055;
            --success: #00ff66;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Rajdhani', sans-serif; }
        
        body { 
            background: linear-gradient(-45deg, #050b14, #0a1128, #000000, #0c0822);
            background-size: 400% 400%;
            animation: gradientBG 15s ease infinite;
            color: var(--text-main); 
            display: flex; 
            min-height: 100vh;
            overflow-x: hidden;
        }

        @keyframes gradientBG {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        .sidebar { 
            width: 290px; 
            background: var(--bg-glass); 
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-right: 1px solid var(--border-glass); 
            padding: 25px 15px; 
            display: flex; 
            flex-direction: column; 
            box-shadow: 5px 0 30px rgba(0,0,0,0.5);
            z-index: 1000;
            transition: left 0.3s ease;
            position: relative;
        }

        .sidebar-close-btn {
            display: none;
            position: absolute;
            top: 15px;
            right: 15px;
            background: rgba(255, 0, 85, 0.15);
            border: 1px solid var(--danger);
            color: var(--danger);
            width: 32px;
            height: 32px;
            border-radius: 8px;
            cursor: pointer;
            align-items: center;
            justify-content: center;
            font-size: 16px;
            transition: all 0.2s;
        }
        .sidebar-close-btn:hover { background: var(--danger); color: #fff; }

        .sidebar-open-btn {
            display: none;
            position: fixed;
            top: 15px;
            left: 15px;
            z-index: 999;
            background: rgba(13, 17, 28, 0.9);
            border: 1px solid var(--primary);
            color: var(--primary);
            width: 42px;
            height: 42px;
            border-radius: 12px;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 0 15px var(--primary-glow);
            font-size: 18px;
        }

        .sidebar-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7);
            backdrop-filter: blur(5px);
            z-index: 999;
        }
        
        .logo-container {
            text-align: center;
            margin-bottom: 25px;
            padding: 10px;
            background: rgba(0, 240, 255, 0.03);
            border: 1px solid rgba(0, 240, 255, 0.15);
            border-radius: 14px;
            box-shadow: inset 0 0 15px rgba(0, 240, 255, 0.05);
        }
        
        .logo-title { 
            font-size: 26px; 
            font-weight: 800; 
            letter-spacing: 3px; 
            text-transform: uppercase; 
            background: linear-gradient(90deg, #00f0ff, #ffffff, #b785ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            filter: drop-shadow(0 0 10px var(--primary-glow));
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .logo-subtitle {
            font-size: 10px;
            color: var(--primary);
            letter-spacing: 5px;
            opacity: 0.8;
            margin-top: 4px;
            font-weight: 700;
        }
        
        .nav-link { 
            display: flex; 
            align-items: center; 
            padding: 12px 18px; 
            color: #a0aec0; 
            text-decoration: none; 
            border-radius: 12px; 
            margin-bottom: 10px; 
            transition: all 0.3s;
            font-size: 17px;
            font-weight: 600;
            border: 1px solid transparent;
        }
        
        .nav-link:hover { 
            background: rgba(0, 240, 255, 0.1); 
            color: #fff; 
            border-color: var(--primary-glow);
            box-shadow: 0 0 15px var(--primary-glow);
            transform: translateX(4px);
        }
        
        .nav-link i { margin-right: 12px; width: 22px; text-align: center; font-size: 18px; }
        
        .main-content { 
            flex: 1; 
            padding: 35px; 
            overflow-y: auto; 
            height: 100vh;
            position: relative;
        }
        
        .header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 30px; 
            padding-bottom: 15px; 
            border-bottom: 1px solid var(--border-glass); 
            gap: 15px;
            flex-wrap: wrap;
        }
        
        .header h2 { font-size: 30px; font-weight: 700; letter-spacing: 1px; }
        
        .card { 
            background: var(--bg-glass); 
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-glass); 
            border-radius: 16px; 
            padding: 25px; 
            margin-bottom: 25px; 
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        
        .card:hover {
            box-shadow: 0 8px 32px 0 var(--primary-glow);
            border-color: rgba(0, 240, 255, 0.3);
        }
        
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }
        
        input, select, textarea { 
            width: 100%; 
            padding: 14px; 
            margin-top: 8px; 
            margin-bottom: 18px; 
            background: rgba(0, 0, 0, 0.5); 
            border: 1px solid var(--border-glass); 
            color: #fff; 
            border-radius: 8px; 
            font-size: 16px;
            transition: all 0.3s;
        }
        
        input:focus, select:focus, textarea:focus { 
            outline: none; 
            border-color: var(--primary); 
            box-shadow: 0 0 15px var(--primary-glow);
            background: rgba(0, 0, 0, 0.7);
        }
        
        .btn { 
            padding: 12px 22px; 
            background: linear-gradient(45deg, #0055ff, var(--primary)); 
            color: #fff; 
            border: none; 
            border-radius: 8px; 
            cursor: pointer; 
            font-weight: 700; 
            font-size: 15px;
            letter-spacing: 1px;
            text-transform: uppercase;
            transition: all 0.3s; 
            text-decoration: none; 
            display: inline-block;
            box-shadow: 0 4px 15px rgba(0, 240, 255, 0.3);
            text-align: center;
        }
        
        .btn:hover { 
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 240, 255, 0.5);
        }
        
        .btn-danger { background: linear-gradient(45deg, #cc0000, var(--danger)); box-shadow: 0 4px 15px rgba(255, 0, 85, 0.3); }
        .btn-danger:hover { box-shadow: 0 8px 25px rgba(255, 0, 85, 0.5); }
        
        .btn-success { background: linear-gradient(45deg, #009933, var(--success)); box-shadow: 0 4px 15px rgba(0, 255, 102, 0.3); }
        .btn-success:hover { box-shadow: 0 8px 25px rgba(0, 255, 102, 0.5); }
        
        .badge { padding: 6px 12px; border-radius: 6px; font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }
        .bg-admin { background: rgba(112, 0, 255, 0.2); color: #b785ff; border: 1px solid #7000ff; box-shadow: 0 0 10px rgba(112,0,255,0.4); }
        .bg-rank { background: rgba(0, 240, 255, 0.2); color: var(--primary); border: 1px solid var(--primary); box-shadow: 0 0 10px var(--primary-glow); }
        
        .table-responsive { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 16px; white-space: nowrap; }
        th, td { padding: 14px; text-align: left; border-bottom: 1px solid var(--border-glass); }
        th { color: var(--primary); text-transform: uppercase; font-size: 14px; letter-spacing: 1px; font-weight: 700; }
        tr:hover td { background: rgba(255,255,255,0.05); }

        optgroup { background: #0a1128; color: var(--primary); }
        option { background: #0a1128; color: #fff; }

        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: #050b14; }
        ::-webkit-scrollbar-thumb { background: var(--primary); border-radius: 4px; }

        /* АДАПТИВНОСТЬ ДЛЯ ТЕЛЕФОНОВ И ПЛАНШЕТОВ */
        @media (max-width: 992px) {
            .grid { grid-template-columns: 1fr !important; }
            .card[style*="grid-column: span 2"] { grid-column: auto !important; }
        }

        @media (max-width: 768px) {
            .sidebar {
                position: fixed;
                top: 0;
                left: -310px;
                height: 100vh;
                width: 280px;
            }
            .sidebar.active { left: 0; }
            .sidebar-close-btn { display: flex; }
            .sidebar-open-btn { display: flex; }
            .sidebar-overlay.active { display: block; }

            .main-content {
                padding: 70px 15px 25px 15px;
                height: auto;
                min-height: 100vh;
            }
            .header {
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
            }
            .header h2 { font-size: 24px; }
            .card { padding: 18px; }
        }
    </style>
</head>
<body>
    <button class="sidebar-open-btn" onclick="toggleSidebar(true)" title="Открыть меню">
        <i class="fa-solid fa-chevron-right"></i>
    </button>
    <div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar(false)"></div>

    {% if user and user.warn_reset_time %}
        {% set elapsed = (now - user.warn_reset_time).total_seconds() %}
        {% if elapsed < 600 %}
            {% set rem_min = ((600 - elapsed) // 60) | int + 1 %}
            <div style="position: fixed; top: 15px; right: 20px; z-index: 9999; background: rgba(255, 0, 85, 0.35); backdrop-filter: blur(10px); border: 1px solid var(--danger); padding: 10px 18px; border-radius: 10px; color: #fff; font-size: 14px; font-weight: bold; box-shadow: 0 0 15px rgba(255, 0, 85, 0.5);">
                <i class="fa-solid fa-triangle-exclamation" style="margin-right: 8px; color: var(--danger);"></i>
                АККАУНТ СБРОШЕН (Скроется через {{ rem_min }} мин)
            </div>
        {% endif %}
    {% endif %}

    {% if user %}
    <div class="sidebar" id="sidebar">
        <button class="sidebar-close-btn" onclick="toggleSidebar(false)">
            <i class="fa-solid fa-xmark"></i>
        </button>

        <div class="logo-container">
            <div class="logo-title">
                <i class="fa-solid fa-star" style="font-size: 14px; color: var(--primary);"></i>
                LORDSHIP
                <i class="fa-solid fa-star" style="font-size: 14px; color: var(--primary);"></i>
            </div>
            <div class="logo-subtitle">COMMAND NETWORK</div>
        </div>
        
        <form action="/search_players" method="GET" style="margin-bottom: 15px;">
            <div style="position: relative;">
                <input type="text" name="q" placeholder="Поиск бойцов..." style="margin:0; padding-right: 40px; font-size: 15px; border-radius: 20px;">
                <button type="submit" style="position: absolute; right: 10px; top: 10px; background: none; border: none; color: var(--primary); cursor: pointer;">
                    <i class="fa-solid fa-magnifying-glass"></i>
                </button>
            </div>
        </form>

        <a href="/" class="nav-link"><i class="fa-solid fa-user-astronaut"></i> Профиль</a>
        <a href="/applications" class="nav-link"><i class="fa-solid fa-file-signature"></i> Заявления</a>
        <a href="/chat/global" class="nav-link"><i class="fa-solid fa-globe"></i> Общий Чат</a>
        
        <div style="font-size: 12px; color: #a0aec0; text-transform: uppercase; margin: 15px 0 5px 10px; font-weight: bold;">Подразделения</div>
        
        {% if is_admin_access %}
            {% for d_name in departments_keys %}
            <a href="/chat/{{ d_name }}" class="nav-link" style="padding: 8px 15px; font-size: 15px;">
                <i class="fa-solid fa-people-group"></i> {{ d_name }}
            </a>
            {% endfor %}
        {% else %}
            {% if user.department != "Нет" %}
            <a href="/chat/{{ user.department }}" class="nav-link" style="padding: 8px 15px; font-size: 15px;">
                <i class="fa-solid fa-people-group"></i> {{ user.department }}
            </a>
            {% else %}
            <div style="font-size: 14px; color: #a0aec0; padding: 5px 15px;">Вы не состоите в отделе</div>
            {% endif %}
        {% endif %}

        {% if user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps') or check_perm(user, 'can_post_news') %}
        <div style="font-size: 12px; color: #b785ff; text-transform: uppercase; margin: 15px 0 5px 10px; font-weight: bold;">Управление</div>
        <a href="/admin" class="nav-link" style="color: #b785ff;"><i class="fa-solid fa-microchip"></i> Админ Панель</a>
        {% endif %}
        
        {% if user.admin_level == "Специальный Администратор" %}
        <a href="/admin/permissions" class="nav-link" style="color: #00f0ff;"><i class="fa-solid fa-sliders"></i> Права Ролей</a>
        <a href="/admin/user_permissions" class="nav-link" style="color: #00f0ff;"><i class="fa-solid fa-user-gear"></i> Права Бойцов</a>
        {% endif %}
        
        <a href="/logout" class="nav-link" style="margin-top: auto; color: var(--danger);"><i class="fa-solid fa-power-off"></i> Выход</a>
    </div>
    {% endif %}
    
    <div class="main-content">
        {% if user and user.is_banned %}
        <div style="background: rgba(255,0,85,0.2); border: 1px solid var(--danger); padding: 15px; border-radius: 12px; margin-bottom: 25px; color: #fff;">
            <i class="fa-solid fa-triangle-exclamation" style="color: var(--danger); margin-right: 10px; font-size: 20px;"></i>
            <strong>АККАУНТ ЗАБЛОКИРОВАН:</strong> 
            {% if user.ban_until and user.ban_until.year < 2099 %}
                До {{ user.ban_until.strftime('%Y-%m-%d %H:%M') }}
            {% else %}
                Бессрочно (Навсегда)
            {% endif %}
            . Отправка рапортов и доступ к чатам ограничены.
        </div>
        {% endif %}

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="card" style="background: rgba(0, 240, 255, 0.1); border-left: 4px solid var(--primary); font-size: 18px;">
                        <i class="fa-solid fa-circle-info" style="color: var(--primary); margin-right: 10px;"></i> {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {% block content %}{% endblock %}
    </div>

    <script>
    function toggleSidebar(open) {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        if (!sidebar) return;
        if (open) {
            sidebar.classList.add('active');
            if (overlay) overlay.classList.add('active');
        } else {
            sidebar.classList.remove('active');
            if (overlay) overlay.classList.remove('active');
        }
    }
    </script>
</body>
</html>
"""

@app.route('/')
@login_required
def index():
    user = get_current_user()
    news = News.query.order_by(News.timestamp.desc()).limit(10).all()
    history = HistoryLog.query.filter_by(user_id=user.id).order_by(HistoryLog.date.desc()).limit(10).all()
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    
    content = """
    <div class="header">
        <h2>ЛИЧНЫЙ ТЕРМИНАЛ</h2>
        <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
            <span class="badge bg-admin">{{ user.admin_level }}</span>
            <span class="badge bg-rank">{{ user.rank }}</span>
            {{ get_epaulette_svg(user.rank) | safe }}
            <span style="font-size: 20px; font-weight: 600;">{{ user.username }} <span style="color: var(--primary);">(EXP: {{ user.exp }})</span></span>
        </div>
    </div>
    
    <div class="grid">
        <div class="card" style="border-top: 3px solid var(--primary);">
            <h3 style="color: var(--primary); margin-bottom: 20px; font-size: 22px;"><i class="fa-solid fa-id-card-clip"></i> ДОСЬЕ ОПЕРАТИВНИКА</h3>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Текущее Звание: <strong style="color:#fff;">{{ user.rank }}</strong> {{ get_epaulette_svg(user.rank) | safe }}</p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Подразделение: <strong style="color:#fff;">{{ user.department }} ({{ user.dept_rank }})</strong></p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Предупреждения (Варны): <strong style="color:var(--danger);">{{ user.warns_count }}/3</strong></p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Успешных операций: <strong style="color:#fff;">{{ user.tasks_completed }}</strong></p>
        </div>
        
        <div class="card" style="border-top: 3px solid var(--secondary); grid-column: span 2;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 10px;">
                <h3 style="color: #b785ff; font-size: 22px;"><i class="fa-solid fa-newspaper"></i> ОФИЦИАЛЬНАЯ ЛЕНТА НОВОСТЕЙ</h3>
                {% if check_perm(user, 'can_post_news') %}
                <a href="/admin" class="btn" style="font-size: 13px; padding: 6px 14px;"><i class="fa-solid fa-plus"></i> Опубликовать новость</a>
                {% endif %}
            </div>
            
            <div>
                {% for item in news %}
                    <div style="background: rgba(0,0,0,0.4); border: 1px solid var(--border-glass); border-left: 4px solid var(--primary); border-radius: 8px; padding: 20px; margin-bottom: 20px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 10px;">
                            <h4 style="color: var(--primary); font-size: 20px;">{{ item.title }}</h4>
                            <div style="display: flex; align-items: center; gap: 15px;">
                                <small style="color: #a0aec0;">[{{ item.timestamp.strftime('%d.%m.%Y %H:%M') }}] // <a href="/profile/{{ item.author_id }}" style="color: var(--primary); text-decoration: none;">{{ item.author.username }}</a></small>
                                
                                {% if (user.id == item.author_id and check_perm(user, 'can_post_news')) or check_perm(user, 'can_delete_all_news') or user.admin_level == "Специальный Администратор" %}
                                <a href="/admin/news/delete/{{ item.id }}" style="color: var(--danger); font-weight: bold; font-size: 14px; text-decoration: none;" onclick="return confirm('Вы уверены, что хотите удалить эту новость?');">
                                    <i class="fa-solid fa-trash"></i> Удалить
                                </a>
                                {% endif %}
                            </div>
                        </div>
                        <p style="font-size: 17px; line-height: 1.5; white-space: pre-wrap;">{{ item.content }}</p>
                    </div>
                {% else %}
                    <p style="color: #a0aec0;">Входящих новостей и приказов от командования нет.</p>
                {% endfor %}
            </div>
        </div>
    </div>

    <div class="card">
        <h3 style="font-size: 22px; margin-bottom: 20px;"><i class="fa-solid fa-clock-rotate-left" style="color: var(--primary);"></i> ИСТОРИЯ СЛУЖБЫ</h3>
        <div class="table-responsive">
            <table>
                <tr><th>Временная метка</th><th>Событие</th></tr>
                {% for log in history %}
                <tr>
                    <td style="width: 180px; color: #a0aec0;">{{ log.date.strftime('%Y-%m-%d %H:%M') }}</td>
                    <td style="font-weight: 500;">{{ log.action }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=user, news=news, history=history, check_perm=check_perm,
        departments_keys=list(DEPARTMENTS.keys()), get_epaulette_svg=get_epaulette_svg,
        is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/search_players')
@login_required
def search_players():
    user = get_current_user()
    query = request.args.get('q', '').strip()
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    results = User.query.filter(User.username.ilike(f'%{query}%')).limit(30).all() if query else []
        
    content = """
    <div class="header"><h2>ПОИСК БОЙЦОВ ПО БАЗЕ ДАННЫХ</h2></div>
    <div class="card">
        <form method="GET" action="/search_players" style="display: flex; gap: 15px; flex-wrap: wrap;">
            <input type="text" name="q" value="{{ query }}" placeholder="Введите никнейм бойца..." required style="margin:0; flex:1;">
            <button type="submit" class="btn"><i class="fa-solid fa-magnifying-glass"></i> ИСКАТЬ</button>
        </form>
    </div>
    <div class="grid">
        {% for u in results %}
        <div class="card" style="border-top: 3px solid var(--primary);">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 15px;">
                <div>
                    <a href="/profile/{{ u.id }}" style="color: #fff; font-size: 22px; font-weight: bold; text-decoration: none;">
                        <i class="fa-solid fa-user"></i> {{ u.username }}
                    </a>
                    <div style="margin-top: 5px;"><span class="badge bg-admin" style="font-size: 11px;">{{ u.admin_level }}</span></div>
                </div>
                <div>{{ get_epaulette_svg(u.rank) | safe }}</div>
            </div>
            <p style="color: #a0aec0; margin-bottom: 5px;">Звание: <strong style="color:#fff;">{{ u.rank }}</strong></p>
            <p style="color: #a0aec0; margin-bottom: 15px;">Отдел: <strong style="color:#fff;">{{ u.department }} ({{ u.dept_rank }})</strong></p>
            <a href="/profile/{{ u.id }}" class="btn" style="width: 100%; font-size: 13px; padding: 8px;"><i class="fa-solid fa-address-card"></i> ОТКРЫТЬ ДОСЬЕ</a>
        </div>
        {% else %}
        {% if query %}<p style="color: #a0aec0; grid-column: 1 / -1;">По запросу "{{ query }}" бойцы не найдены.</p>{% endif %}
        {% endfor %}
    </div>
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=user, query=query, results=results, check_perm=check_perm,
        departments_keys=list(DEPARTMENTS.keys()), get_epaulette_svg=get_epaulette_svg,
        is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/profile/<int:user_id>')
@login_required
def view_profile(user_id):
    current_u = get_current_user()
    target = db.session.get(User, user_id)
    if not target: abort(404)
        
    history = HistoryLog.query.filter_by(user_id=target.id).order_by(HistoryLog.date.desc()).all()
    is_admin_access = current_u.admin_level != "Нет" or check_perm(current_u, 'can_view_apps') or check_perm(current_u, 'can_approve_apps')
    
    content = """
    <div class="header">
        <h2>ПРОФИЛЬ БОЙЦА: <span style="color: var(--primary);">{{ target.username }}</span></h2>
        <div>{{ get_epaulette_svg(target.rank) | safe }}</div>
    </div>
    <div class="grid">
        <div class="card" style="border-top: 3px solid var(--primary);">
            <h3 style="margin-bottom: 20px;"><i class="fa-solid fa-address-card" style="color: var(--primary);"></i> ОБЩАЯ ИНФОРМАЦИЯ</h3>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Возраст (ООС): <strong style="color:#fff;">{{ target.age }}</strong></p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Текущее Звание: <strong style="color:#fff;">{{ target.rank }}</strong> {{ get_epaulette_svg(target.rank) | safe }} <span style="color: var(--primary);">(EXP: {{ target.exp }})</span></p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Подразделение: <strong style="color:#fff;">{{ target.department }} - {{ target.dept_rank }}</strong></p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Уровень доступа: <strong style="color:#fff;">{{ target.admin_level }}</strong></p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Предупреждения (Варны): <strong style="color:var(--danger);">{{ target.warns_count }}/3</strong></p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Статус блокировки: 
                {% if target.is_banned %}<strong style="color:var(--danger);">ЗАБЛОКИРОВАН (до {{ target.ban_until.strftime('%Y-%m-%d') if target.ban_until else 'Навсегда' }})</strong>
                {% else %}<strong style="color:var(--success);">Активен</strong>{% endif %}
            </p>
            <p style="font-size: 18px; margin-bottom: 10px; color: #a0aec0;">Статус мута: 
                {% if target.is_muted %}<strong style="color:#ffd700;">МУТ ЧАТА (до {{ target.mute_until.strftime('%Y-%m-%d %H:%M') if target.mute_until else 'Навсегда' }})</strong>
                {% else %}<strong style="color:var(--success);">Нет ограничений</strong>{% endif %}
            </p>
        </div>
        
        {% if check_perm(current_u, 'can_mute') or check_perm(current_u, 'can_ban') or check_perm(current_u, 'can_warn') %}
        <div class="card" style="border-top: 3px solid var(--danger);">
            <h3 style="color: var(--danger); margin-bottom: 20px;"><i class="fa-solid fa-gavel"></i> ПАНЕЛЬ ДИСЦИПЛИНАРНЫХ МЕР</h3>
            <form method="POST" action="/admin/sanction/{{ target.id }}">
                <label style="color: #a0aec0; font-weight: bold;">Вид наказания</label>
                <select name="sanction_type" required>
                    {% if check_perm(current_u, 'can_warn') %}<option value="warn">Выдать Варн (Предупреждение)</option>{% endif %}
                    {% if check_perm(current_u, 'can_mute') %}
                        <option value="mute">Выдать Мут чата</option>
                        <option value="unmute">Снять Мут чата</option>
                    {% endif %}
                    {% if check_perm(current_u, 'can_ban') %}
                        <option value="ban">Заблокировать аккаунт (Бан)</option>
                        <option value="unban">Разблокировать аккаунт (Разбан)</option>
                    {% endif %}
                </select>
                <label style="color: #a0aec0; font-weight: bold;">Срок действия</label>
                <select name="duration">
                    <option value="3d">3 Дня</option>
                    <option value="7d">7 Дней</option>
                    <option value="30d">30 Дней</option>
                    <option value="forever">Навсегда (Бессрочно)</option>
                </select>
                <button type="submit" class="btn btn-danger" style="width: 100%; margin-top: 10px;"><i class="fa-solid fa-gavel"></i> ПРИМЕНИТЬ НАКАЗАНИЕ</button>
            </form>
        </div>
        {% endif %}
    </div>

    {% if check_perm(current_u, 'can_view_history') %}
    <div class="card">
        <h3 style="margin-bottom: 20px;"><i class="fa-solid fa-history" style="color: var(--primary);"></i> ПОЛНЫЙ ЛОГ СОБЫТИЙ БОЙЦА</h3>
        <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
            <table>
                {% for log in history %}
                <tr>
                    <td style="color: #a0aec0; width: 180px;">[{{ log.date.strftime('%Y-%m-%d %H:%M') }}]</td>
                    <td>{{ log.action }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </div>
    {% endif %}
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=current_u, target=target, history=history, current_u=current_u, check_perm=check_perm,
        departments_keys=list(DEPARTMENTS.keys()), get_epaulette_svg=get_epaulette_svg,
        is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/applications', methods=['GET', 'POST'])
@login_required
def applications():
    user = get_current_user()
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    
    if request.method == 'POST':
        if is_user_banned(user):
            flash("Ваш аккаунт заблокирован. Подача рапортов невозможна.")
            return redirect(url_for('applications'))

        app_type = request.form.get('app_type')
        proof = request.form.get('proof')
        
        if app_type == "Повышение": target = request.form.get('exp_target')
        elif app_type == "Вступление": target = request.form.get('dept_target')
        else: target = request.form.get('complaint_target', 'Дисциплинарная жалоба')

        new_app = Application(user_id=user.id, app_type=app_type, target=target, proof_url=proof)
        db.session.add(new_app)
        db.session.commit()
        log_history(user.id, f"Подано заявление: {app_type} ({target})")
        flash("Рапорт успешно передан в штаб!")
        return redirect(url_for('applications'))

    my_apps = Application.query.filter_by(user_id=user.id).order_by(Application.date_created.desc()).all()
    
    content = """
    <div class="header"><h2>ЦЕНТР ЗАЯВЛЕНИЙ</h2></div>
    <div class="grid">
        <div class="card">
            <h3 style="margin-bottom: 20px; font-size: 22px;"><i class="fa-solid fa-pen-to-square" style="color: var(--primary);"></i> СОЗДАТЬ РАПОРТ</h3>
            <form method="POST">
                <label style="color: #a0aec0; font-weight: bold; text-transform: uppercase; font-size: 14px;">Категория рапорта</label>
                <select name="app_type" id="app_type" onchange="updateForm()">
                    <option value="Повышение">Отчет на повышение (Запрос EXP)</option>
                    <option value="Вступление">Перевод / Вступление в подразделение</option>
                    <option value="Жалоба">Дисциплинарная жалоба</option>
                </select>

                <div id="target_exp_box">
                    <label style="color: #a0aec0; font-weight: bold; text-transform: uppercase; font-size: 14px;">Запрашиваемый опыт (EXP)</label>
                    <select name="exp_target">
                        <option value="5">5 EXP</option><option value="10">10 EXP</option>
                        <option value="15">15 EXP</option><option value="20">20 EXP</option>
                        <option value="25">25 EXP</option><option value="30">30 EXP</option>
                    </select>
                </div>
                
                <div id="target_dept_box" style="display:none;">
                    <label style="color: #a0aec0; font-weight: bold; text-transform: uppercase; font-size: 14px;">Целевое подразделение</label>
                    <select name="dept_target">
                        <option value="Штурмовики">Штурмовики</option>
                        <option value="Разведка">Разведка</option>
                        <option value="Моб.Группа">Моб.Группа</option>
                        <option value="ОС">Офицерский Состав (Мин. ранг: Майор)</option>
                    </select>
                </div>

                <div id="target_complaint_box" style="display:none;">
                    <label style="color: #a0aec0; font-weight: bold; text-transform: uppercase; font-size: 14px;">Имя нарушителя</label>
                    <input type="text" name="complaint_target" placeholder="Введите никнейм сотрудника">
                </div>

                <label style="color: #a0aec0; font-weight: bold; text-transform: uppercase; font-size: 14px;">Материалы дела</label>
                <textarea name="proof" rows="4" placeholder="Вставьте ссылки на доказательства..." required></textarea>

                <button type="submit" class="btn" style="width: 100%;" {% if user.is_banned %}disabled style="opacity:0.5;"{% endif %}><i class="fa-solid fa-satellite-dish"></i> ОТПРАВИТЬ В ШТАБ</button>
            </form>
        </div>
        
        <div class="card">
            <h3 style="margin-bottom: 20px; font-size: 22px;"><i class="fa-solid fa-folder-open" style="color: var(--primary);"></i> АРХИВ МОИХ РАПОРТОВ</h3>
            <div class="table-responsive">
                <table>
                    <tr><th>Тип</th><th>Цель</th><th>Статус</th></tr>
                    {% for app in apps %}
                    <tr>
                        <td>{{ app.app_type }}</td>
                        <td><strong style="color: #fff;">{{ app.target }}</strong></td>
                        <td>
                            {% if app.status == 'Ожидает' %}<span style="color: #ffd700; font-weight: bold;">{{ app.status }}</span>
                            {% elif app.status == 'Одобрено' %}<span style="color: var(--success); font-weight: bold;">{{ app.status }}</span>
                            {% else %}<span style="color: var(--danger); font-weight: bold;">{{ app.status }}</span>{% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </div>
    <script>
    function updateForm() {
        var type = document.getElementById('app_type').value;
        document.getElementById('target_exp_box').style.display = (type === 'Повышение') ? 'block' : 'none';
        document.getElementById('target_dept_box').style.display = (type === 'Вступление') ? 'block' : 'none';
        document.getElementById('target_complaint_box').style.display = (type === 'Жалоба') ? 'block' : 'none';
    }
    </script>
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=user, apps=my_apps, check_perm=check_perm,
        departments_keys=list(DEPARTMENTS.keys()), get_epaulette_svg=get_epaulette_svg,
        is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/admin')
@login_required
def admin_panel():
    user = get_current_user()
    if not (check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps') or check_perm(user, 'can_force_action') or check_perm(user, 'can_post_news')):
        abort(403)

    pending_apps = Application.query.filter_by(status="Ожидает").order_by(Application.date_created.desc()).all()
    all_users = User.query.order_by(User.username).all()
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    
    content = """
    <div class="header" style="border-bottom-color: rgba(112,0,255,0.3);">
        <h2 style="color: #b785ff; text-shadow: 0 0 15px rgba(112,0,255,0.5);"><i class="fa-solid fa-microchip"></i> ПАНЕЛЬ УПРАВЛЕНИЯ</h2>
        <span class="badge bg-admin" style="font-size: 16px;">УРОВЕНЬ ДОСТУПА: {{ user.admin_level }}</span>
    </div>
    <div class="grid">
        <div class="card" style="grid-column: 1 / -1; border-top: 3px solid #b785ff;">
            <h3 style="margin-bottom: 20px; font-size: 22px;"><i class="fa-solid fa-inbox" style="color: #b785ff;"></i> РАПОРТЫ НА РАССМОТРЕНИИ</h3>
            <div class="table-responsive">
                <table>
                    <tr><th>Боец</th><th>Категория</th><th>Запрос</th><th>Материалы</th><th>Резолюция</th></tr>
                    {% for app in pending_apps %}
                    <tr>
                        <td><a href="/profile/{{ app.user.id }}" style="color: var(--primary); text-decoration: none; font-weight: bold; font-size: 18px;"><i class="fa-solid fa-user-magnifying-glass"></i> {{ app.user.username }}</a></td>
                        <td>{{ app.app_type }}</td>
                        <td><strong style="color: #fff;">{{ app.target }}</strong></td>
                        <td>
                            <a href="/admin/application/{{ app.id }}" class="btn" style="padding: 6px 14px; font-size: 13px; background: rgba(0,240,255,0.2); border: 1px solid var(--primary);">
                                <i class="fa-solid fa-eye"></i> Изучить рапорт
                            </a>
                        </td>
                        <td>
                            {% if check_perm(user, 'can_approve_apps') %}
                                {% if app.user_id != user.id or user.admin_level == "Специальный Администратор" %}
                                <a href="/admin/resolve/{{ app.id }}/approve" class="btn btn-success" style="padding: 8px 12px; font-size: 14px;"><i class="fa-solid fa-check"></i> Принять</a>
                                <a href="/admin/resolve/{{ app.id }}/reject" class="btn btn-danger" style="padding: 8px 12px; font-size: 14px;"><i class="fa-solid fa-xmark"></i> Отклонить</a>
                                {% else %}<small style="color: var(--danger); font-weight: bold;"><i class="fa-solid fa-lock"></i> Свой рапорт</small>{% endif %}
                            {% else %}<small style="color: #a0aec0;">[Только просмотр]</small>{% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>

        {% if check_perm(user, 'can_post_news') %}
        <div class="card" style="grid-column: 1 / -1; border-top: 3px solid var(--primary);">
            <h3 style="color: var(--primary); margin-bottom: 20px;"><i class="fa-solid fa-bullhorn"></i> ПУБЛИКАЦИЯ НОВОСТЕЙ И ПРИКАЗОВ</h3>
            <form method="POST" action="/admin/news/add">
                <label style="color: #a0aec0; font-weight: bold;">Заголовок</label>
                <input type="text" name="news_title" placeholder="Введите заголовок..." required>
                <label style="color: #a0aec0; font-weight: bold;">Текст новости</label>
                <textarea name="news_content" rows="4" placeholder="Введите текст обращения..." required></textarea>
                <button type="submit" class="btn" style="width: 100%;"><i class="fa-solid fa-paper-plane"></i> ОПУБЛИКОВАТЬ В ЛЕНТУ</button>
            </form>
        </div>
        {% endif %}
        
        {% if check_perm(user, 'can_force_action') %}
        <div class="card" style="grid-column: 1 / -1; border: 1px solid var(--danger); background: rgba(255,0,85,0.05);">
            <h3 style="color: var(--danger); margin-bottom: 20px; font-size: 22px;"><i class="fa-solid fa-triangle-exclamation"></i> ТЕРМИНАЛ ПРИНУДИТЕЛЬНЫХ ДЕЙСТВИЙ</h3>
            <form method="POST" action="/admin/force_action">
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; align-items: end;">
                    <div>
                        <label style="color: #ffb3cc; font-weight: bold; font-size: 14px;">Поиск бойца</label>
                        <input type="text" name="target_username" list="user_nicknames_list" placeholder="Никнейм..." required style="margin:0;">
                        <datalist id="user_nicknames_list">
                            {% for u in all_users %}
                            <option value="{{ u.username }}">{{ u.username }} [Ранг: {{ u.rank }}]</option>
                            {% endfor %}
                        </datalist>
                    </div>
                    <div>
                        <label style="color: #ffb3cc; font-weight: bold; font-size: 14px;">Директива</label>
                        <select name="action_type" id="force_action_type" onchange="updateForceFields()" style="margin:0;">
                            <option value="add_exp">Начислить EXP</option>
                            <option value="set_rank">Назначить звание</option>
                            <option value="set_admin">Выдать уровень доступа (Админ)</option>
                            <option value="set_dept">Назначить в отдел</option>
                            <option value="set_dept_rank">Выдать ранг в отделе</option>
                            <option value="fire">Отстранить от отдела</option>
                        </select>
                    </div>

                    <div id="field_exp">
                        <label style="color: #ffb3cc; font-weight: bold; font-size: 14px;">Количество EXP</label>
                        <input type="number" name="val_exp" value="10" style="margin:0;">
                    </div>

                    <div id="field_rank" style="display:none;">
                        <label style="color: #ffb3cc; font-weight: bold; font-size: 14px;">Звание</label>
                        <select name="val_rank" style="margin:0;">
                            <optgroup label="Обычные звания">
                                {% for r in all_ranks %}<option value="{{ r }}">{{ r }}</option>{% endfor %}
                            </optgroup>
                            <optgroup label="Специальные звания">
                                {% for sr in special_ranks %}<option value="{{ sr }}">{{ sr }}</option>{% endfor %}
                            </optgroup>
                        </select>
                    </div>

                    <div id="field_admin" style="display:none;">
                        <label style="color: #ffb3cc; font-weight: bold; font-size: 14px;">Админ уровень</label>
                        <select name="val_admin" style="margin:0;">
                            {% for al in admin_levels %}<option value="{{ al }}">{{ al }}</option>{% endfor %}
                        </select>
                    </div>

                    <div id="field_dept" style="display:none;">
                        <label style="color: #ffb3cc; font-weight: bold; font-size: 14px;">Отдел</label>
                        <select name="val_dept" style="margin:0;">
                            {% for d in departments_keys %}<option value="{{ d }}">{{ d }}</option>{% endfor %}
                        </select>
                    </div>

                    <div id="field_dept_rank" style="display:none;">
                        <label style="color: #ffb3cc; font-weight: bold; font-size: 14px;">Ранг в отделе</label>
                        <select name="val_dept_rank" style="margin:0;">
                            {% for d, ranks in departments_dict.items() %}
                                <optgroup label="Отдел: {{ d }}">
                                    {% for dr in ranks %}<option value="{{ dr }}">{{ d }} — {{ dr }}</option>{% endfor %}
                                </optgroup>
                            {% endfor %}
                        </select>
                    </div>

                    <div style="grid-column: 1 / -1; margin-top: 10px;">
                        <button type="submit" class="btn btn-danger" style="width: 100%; height: 50px;"><i class="fa-solid fa-bolt"></i> ИСПОЛНИТЬ ДИРЕКТИВУ</button>
                    </div>
                </div>
            </form>
        </div>
        {% endif %}
    </div>
    <script>
    function updateForceFields() {
        var act = document.getElementById('force_action_type').value;
        document.getElementById('field_exp').style.display = (act === 'add_exp') ? 'block' : 'none';
        document.getElementById('field_rank').style.display = (act === 'set_rank') ? 'block' : 'none';
        document.getElementById('field_admin').style.display = (act === 'set_admin') ? 'block' : 'none';
        document.getElementById('field_dept').style.display = (act === 'set_dept') ? 'block' : 'none';
        document.getElementById('field_dept_rank').style.display = (act === 'set_dept_rank') ? 'block' : 'none';
    }
    </script>
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=user, pending_apps=pending_apps, all_users=all_users,
        all_ranks=list(RANKS_EXP.keys()), special_ranks=SPECIAL_RANKS,
        admin_levels=ADMIN_LEVELS, departments_keys=list(DEPARTMENTS.keys()),
        departments_dict=DEPARTMENTS, check_perm=check_perm,
        get_epaulette_svg=get_epaulette_svg, is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/admin/news/add', methods=['POST'])
@login_required
def add_news():
    user = get_current_user()
    if not check_perm(user, 'can_post_news'): abort(403)
    title = request.form.get('news_title', '').strip()
    content = request.form.get('news_content', '').strip()
    if title and content:
        n = News(title=title, content=content, author_id=user.id)
        db.session.add(n)
        db.session.commit()
        log_history(user.id, f"Опубликована новость: '{title}'")
        flash("Новость успешно опубликована!")
    return redirect(url_for('index'))

@app.route('/admin/news/delete/<int:news_id>')
@login_required
def delete_news(news_id):
    user = get_current_user()
    news_item = db.session.get(News, news_id)
    if not news_item: abort(404)
        
    can_delete = (news_item.author_id == user.id and check_perm(user, 'can_post_news')) or check_perm(user, 'can_delete_all_news') or user.admin_level == "Специальный Администратор"
    if not can_delete:
        flash("У вас нет полномочий для удаления этой новости!")
        return redirect(url_for('index'))
        
    db.session.delete(news_item)
    db.session.commit()
    log_history(user.id, f"Удалена новость: '{news_item.title}'")
    flash("Новость успешно удалена!")
    return redirect(url_for('index'))

@app.route('/admin/permissions', methods=['GET', 'POST'])
@login_required
def admin_permissions():
    user = get_current_user()
    if user.admin_level != "Специальный Администратор": abort(403)
        
    if request.method == 'POST':
        for r_name in ALL_ROLES_LIST:
            perm = RolePermission.query.filter_by(role_name=r_name).first()
            if not perm:
                perm = RolePermission(role_name=r_name)
                db.session.add(perm)
                
            perm.can_view_apps = (f'can_view_apps_{r_name}' in request.form)
            perm.can_approve_apps = (f'can_approve_apps_{r_name}' in request.form)
            perm.can_mute = (f'can_mute_{r_name}' in request.form)
            perm.can_ban = (f'can_ban_{r_name}' in request.form)
            perm.can_warn = (f'can_warn_{r_name}' in request.form)
            perm.can_force_action = (f'can_force_action_{r_name}' in request.form)
            perm.can_post_news = (f'can_post_news_{r_name}' in request.form)
            perm.can_delete_all_news = (f'can_delete_all_news_{r_name}' in request.form)
            perm.can_view_history = (f'can_view_history_{r_name}' in request.form)
            
        db.session.commit()
        flash("Настройки полномочий ролей успешно сохранены!")
        return redirect(url_for('admin_permissions'))
        
    permissions = RolePermission.query.order_by(RolePermission.id.asc()).all()
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    
    content = """
    <div class="header"><h2 style="color: var(--primary);"><i class="fa-solid fa-sliders"></i> НАСТРОЙКА ПОЛНОМОЧИЙ ПО РОЛЯМ</h2></div>
    <div class="card" style="border-top: 3px solid var(--primary);">
        <form method="POST">
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>Ранг / Роль</th>
                            <th>Просмотр рапортов</th><th>Одобрение рапортов</th><th>Мут</th>
                            <th>Бан</th><th>Варн</th><th>Принуд. Терминал</th>
                            <th>Публикация новостей</th><th>Удаление ВСЕХ новостей</th><th>Логи</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for p in permissions %}
                        <tr>
                            <td><strong style="color: #fff; font-size: 18px;">{{ p.role_name }}</strong></td>
                            <td><input type="checkbox" name="can_view_apps_{{ p.role_name }}" {% if p.can_view_apps %}checked{% endif %} style="width:20px; height:20px;"></td>
                            <td><input type="checkbox" name="can_approve_apps_{{ p.role_name }}" {% if p.can_approve_apps %}checked{% endif %} style="width:20px; height:20px;"></td>
                            <td><input type="checkbox" name="can_mute_{{ p.role_name }}" {% if p.can_mute %}checked{% endif %} style="width:20px; height:20px;"></td>
                            <td><input type="checkbox" name="can_ban_{{ p.role_name }}" {% if p.can_ban %}checked{% endif %} style="width:20px; height:20px;"></td>
                            <td><input type="checkbox" name="can_warn_{{ p.role_name }}" {% if p.can_warn %}checked{% endif %} style="width:20px; height:20px;"></td>
                            <td><input type="checkbox" name="can_force_action_{{ p.role_name }}" {% if p.can_force_action %}checked{% endif %} style="width:20px; height:20px;"></td>
                            <td><input type="checkbox" name="can_post_news_{{ p.role_name }}" {% if p.can_post_news %}checked{% endif %} style="width:20px; height:20px;"></td>
                            <td><input type="checkbox" name="can_delete_all_news_{{ p.role_name }}" {% if p.can_delete_all_news %}checked{% endif %} style="width:20px; height:20px;"></td>
                            <td><input type="checkbox" name="can_view_history_{{ p.role_name }}" {% if p.can_view_history %}checked{% endif %} style="width:20px; height:20px;"></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <button type="submit" class="btn btn-success" style="margin-top: 25px; width: 100%; height: 50px;"><i class="fa-solid fa-save"></i> СОХРАНИТЬ ВСЕ НАСТРОЙКИ</button>
        </form>
    </div>
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=user, permissions=permissions, check_perm=check_perm,
        departments_keys=list(DEPARTMENTS.keys()), get_epaulette_svg=get_epaulette_svg,
        is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/admin/user_permissions', methods=['GET', 'POST'])
@login_required
def admin_user_permissions():
    user = get_current_user()
    if user.admin_level != "Специальный Администратор": abort(403)
        
    all_users = User.query.order_by(User.username).all()
    selected_username = request.args.get('username', '').strip()
    selected_user = User.query.filter_by(username=selected_username).first() if selected_username else None
    override = UserPermissionOverride.query.filter_by(user_id=selected_user.id).first() if selected_user else None
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')

    if request.method == 'POST':
        target_uid = request.form.get('target_user_id')
        selected_user = db.session.get(User, target_uid)
        if selected_user:
            override = UserPermissionOverride.query.filter_by(user_id=selected_user.id).first()
            if not override:
                override = UserPermissionOverride(user_id=selected_user.id)
                db.session.add(override)
                
            override.can_view_apps = ('can_view_apps' in request.form)
            override.can_approve_apps = ('can_approve_apps' in request.form)
            override.can_mute = ('can_mute' in request.form)
            override.can_ban = ('can_ban' in request.form)
            override.can_warn = ('can_warn' in request.form)
            override.can_force_action = ('can_force_action' in request.form)
            override.can_post_news = ('can_post_news' in request.form)
            override.can_delete_all_news = ('can_delete_all_news' in request.form)
            override.can_view_history = ('can_view_history' in request.form)
            
            db.session.commit()
            flash(f"Индивидуальные права для {selected_user.username} успешно обновлены!")
            return redirect(url_for('admin_user_permissions', username=selected_user.username))

    content = """
    <div class="header"><h2 style="color: var(--primary);"><i class="fa-solid fa-user-gear"></i> ИНДИВИДУАЛЬНЫЕ ПРАВА БОЙЦОВ</h2></div>
    <div class="card" style="border-top: 3px solid var(--primary);">
        <form method="GET" action="/admin/user_permissions" style="display: flex; gap: 15px; flex-wrap: wrap;">
            <input type="text" name="username" list="user_search_list" value="{{ selected_username }}" placeholder="Введите никнейм..." required style="margin:0; flex:1;">
            <datalist id="user_search_list">
                {% for u in all_users %}<option value="{{ u.username }}">{{ u.username }} [Ранг: {{ u.rank }}]</option>{% endfor %}
            </datalist>
            <button type="submit" class="btn"><i class="fa-solid fa-filter"></i> ЗАГРУЗИТЬ ПРАВА</button>
        </form>
    </div>

    {% if selected_user %}
    <div class="card" style="border-top: 3px solid var(--secondary);">
        <h3 style="color: #b785ff; margin-bottom: 20px;">НАСТРОЙКА ПРАВ ДЛЯ: <span style="color:#fff;">{{ selected_user.username }}</span> [{{ selected_user.rank }}]</h3>
        <form method="POST">
            <input type="hidden" name="target_user_id" value="{{ selected_user.id }}">
            <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));">
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_view_apps" {% if override and override.can_view_apps %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Просмотр рапортов</label></div>
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_approve_apps" {% if override and override.can_approve_apps %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Одобрение рапортов</label></div>
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_mute" {% if override and override.can_mute %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Выдача Мута</label></div>
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_ban" {% if override and override.can_ban %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Выдача Бана</label></div>
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_warn" {% if override and override.can_warn %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Выдача Варна</label></div>
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_force_action" {% if override and override.can_force_action %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Принуд. Терминал</label></div>
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_post_news" {% if override and override.can_post_news %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Публикация новостей</label></div>
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_delete_all_news" {% if override and override.can_delete_all_news %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Удаление ВСЕХ новостей</label></div>
                <div><label style="display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 18px;"><input type="checkbox" name="can_view_history" {% if override and override.can_view_history %}checked{% endif %} style="width:20px; height:20px; margin:0;"> Просмотр Логов</label></div>
            </div>
            <button type="submit" class="btn btn-success" style="margin-top: 25px; width: 100%; height: 50px;"><i class="fa-solid fa-save"></i> СОХРАНИТЬ ПРАВА БОЙЦА</button>
        </form>
    </div>
    {% endif %}
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=user, all_users=all_users, selected_username=selected_username,
        selected_user=selected_user, override=override, check_perm=check_perm,
        departments_keys=list(DEPARTMENTS.keys()), get_epaulette_svg=get_epaulette_svg,
        is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/admin/application/<int:app_id>')
@login_required
def view_application(app_id):
    user = get_current_user()
    if not (check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')): abort(403)
        
    application = db.session.get(Application, app_id)
    if not application: abort(404)
        
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    
    content = """
    <div class="header">
        <h2><a href="/admin" style="color: #a0aec0; text-decoration: none; font-size: 24px;"><i class="fa-solid fa-arrow-left"></i></a> ДЕТАЛИ РАПОРТА #{{ application.id }}</h2>
    </div>
    <div class="card" style="border-top: 3px solid var(--primary);">
        <p style="font-size: 18px; margin-bottom: 12px; color: #a0aec0;">Заявитель: <a href="/profile/{{ application.user.id }}" style="color:#fff; font-weight: bold;">{{ application.user.username }}</a> [{{ application.user.rank }}]</p>
        <p style="font-size: 18px; margin-bottom: 12px; color: #a0aec0;">Тип рапорта: <strong style="color:#fff;">{{ application.app_type }}</strong></p>
        <p style="font-size: 18px; margin-bottom: 12px; color: #a0aec0;">Запрос / Отдел: <strong style="color:var(--primary);">{{ application.target }}</strong></p>
        <div style="background: rgba(0,0,0,0.5); padding: 20px; border-radius: 8px; font-size: 18px; white-space: pre-wrap; margin-top: 15px;">{{ application.proof_url }}</div>

        {% if application.status == 'Ожидает' %}
        <div style="margin-top: 30px; display: flex; gap: 15px; flex-wrap: wrap;">
            {% if check_perm(user, 'can_approve_apps') %}
                {% if application.user_id != user.id or user.admin_level == "Специальный Администратор" %}
                <a href="/admin/resolve/{{ application.id }}/approve" class="btn btn-success"><i class="fa-solid fa-check"></i> Одобрить</a>
                <a href="/admin/resolve/{{ application.id }}/reject" class="btn btn-danger"><i class="fa-solid fa-xmark"></i> Отклонить</a>
                {% else %}<p style="color: var(--danger); font-weight: bold;">Вы не можете проверять свой рапорт.</p>{% endif %}
            {% endif %}
        </div>
        {% endif %}
    </div>
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=user, application=application, check_perm=check_perm,
        departments_keys=list(DEPARTMENTS.keys()), get_epaulette_svg=get_epaulette_svg,
        is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/admin/resolve/<int:app_id>/<action>')
@login_required
def resolve_app(app_id, action):
    admin = get_current_user()
    if not check_perm(admin, 'can_approve_apps'): abort(403)
        
    application = db.session.get(Application, app_id)
    if not application: abort(404)
    if application.user_id == admin.id and admin.admin_level != "Специальный Администратор":
        flash("Проверка собственных рапортов запрещена.")
        return redirect(url_for('admin_panel'))
        
    target_user = db.session.get(User, application.user_id)
    if action == 'approve':
        application.status = "Одобрено"
        target_user.tasks_completed += 1
        if application.app_type == "Повышение":
            try:
                exp_gained = int(application.target)
                target_user.exp += exp_gained
                log_history(target_user.id, f"Рапорт одобрен {admin.username}. Начислено {exp_gained} EXP.")
                recalculate_rank(target_user)
            except ValueError: pass
        elif application.app_type == "Вступление":
            dept = application.target
            target_user.department = dept
            target_user.dept_rank = DEPARTMENTS[dept][0]
            log_history(target_user.id, f"Переведен в отдел '{dept}' офицером {admin.username}")
    else:
        application.status = "Отклонено"
        log_history(target_user.id, f"Рапорт ({application.app_type}) отклонен офицером {admin.username}")
        
    db.session.commit()
    flash("Резолюция применена.")
    return redirect(url_for('admin_panel'))

@app.route('/admin/sanction/<int:user_id>', methods=['POST'])
@login_required
def apply_sanction(user_id):
    admin = get_current_user()
    target = db.session.get(User, user_id)
    if not target: abort(404)
        
    can_s, err_msg = can_sanction_target(admin, target)
    if not can_s:
        flash(err_msg)
        return redirect(url_for('view_profile', user_id=user_id))

    s_type = request.form.get('sanction_type')
    duration = request.form.get('duration')
    
    until_dt = None
    if duration == '3d': until_dt = datetime.utcnow() + timedelta(days=3)
    elif duration == '7d': until_dt = datetime.utcnow() + timedelta(days=7)
    elif duration == '30d': until_dt = datetime.utcnow() + timedelta(days=30)
    elif duration == 'forever': until_dt = datetime(2099, 12, 31)

    if s_type == 'ban':
        if not check_perm(admin, 'can_ban'): abort(403)
        target.is_banned = True
        target.ban_until = until_dt
        log_history(target.id, f"БАН от {admin.username} ({duration})")
    elif s_type == 'unban':
        if not check_perm(admin, 'can_ban'): abort(403)
        target.is_banned = False
        target.ban_until = None
        log_history(target.id, f"Разбан от {admin.username}")
    elif s_type == 'mute':
        if not check_perm(admin, 'can_mute'): abort(403)
        target.is_muted = True
        target.mute_until = until_dt
        log_history(target.id, f"МУТ от {admin.username} ({duration})")
    elif s_type == 'unmute':
        if not check_perm(admin, 'can_mute'): abort(403)
        target.is_muted = False
        target.mute_until = None
        log_history(target.id, f"Снятие мута от {admin.username}")
    elif s_type == 'warn':
        if not check_perm(admin, 'can_warn'): abort(403)
        target.warns_count += 1
        log_history(target.id, f"ВАРН ({target.warns_count}/3) от {admin.username}")
        if target.warns_count >= 3:
            target.rank = "Стажер"
            target.exp = 0
            target.department = "Нет"
            target.dept_rank = "Нет"
            target.warns_count = 0
            target.warn_reset_flag = True
            target.warn_reset_time = datetime.utcnow()
            log_history(target.id, "СБРОС АККАУНТА ИЗ-ЗА 3 ВАРНОВ!")

    db.session.commit()
    return redirect(url_for('view_profile', user_id=user_id))

@app.route('/admin/force_action', methods=['POST'])
@login_required
def force_action():
    admin = get_current_user()
    if not check_perm(admin, 'can_force_action'): abort(403)
        
    target_username = request.form.get('target_username')
    a_type = request.form.get('action_type')
    target_user = User.query.filter_by(username=target_username).first()
    if not target_user:
        flash("Боец не найден.")
        return redirect(url_for('admin_panel'))
        
    if a_type == "add_exp":
        val = int(request.form.get('val_exp', 0))
        target_user.exp += val
        log_history(target_user.id, f"Директива: +{val} EXP от {admin.username}.")
        recalculate_rank(target_user)
    elif a_type == "set_rank":
        val = request.form.get('val_rank')
        target_user.rank = val
        log_history(target_user.id, f"Директива: звание {val} от {admin.username}.")
    elif a_type == "set_admin":
        val = request.form.get('val_admin')
        target_user.admin_level = val
        log_history(target_user.id, f"Директива: админка {val} от {admin.username}.")
    elif a_type == "set_dept":
        val = request.form.get('val_dept')
        target_user.department = val
        target_user.dept_rank = DEPARTMENTS.get(val, ["Нет"])[0]
        log_history(target_user.id, f"Директива: отдел {val} от {admin.username}.")
    elif a_type == "fire":
        target_user.department = "Нет"
        target_user.dept_rank = "Нет"
        log_history(target_user.id, f"Директива: уволен из отдела от {admin.username}.")
        
    db.session.commit()
    flash(f"Директива применена к {target_user.username}.")
    return redirect(url_for('admin_panel'))

# =======================
# ЧАТ И LIVE-API
# =======================
@app.route('/chat/<channel>')
@login_required
def chat_view(channel):
    user = get_current_user()
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    
    if channel != "global" and channel != "news" and channel != user.department and not is_admin_access:
        abort(403)
        
    content = """
    <div class="header"><h2>ЧАТ KAНАЛА: <span style="color: var(--primary);">{{ channel }}</span></h2></div>
    <div class="card" style="height: 65vh; display: flex; flex-direction: column; padding: 0; overflow: hidden; border-top: 3px solid var(--primary);">
        <div id="chatMessages" style="flex: 1; overflow-y: auto; padding: 20px;"></div>
        {% if not user.is_banned and not user.is_muted %}
        <form id="chatForm" style="padding: 15px; background: rgba(13, 17, 28, 0.9); border-top: 1px solid var(--border-glass); display: flex; gap: 10px;">
            <input type="text" id="chatInput" placeholder="Введите сообщение..." required style="margin: 0; flex: 1; font-size: 16px;">
            <button type="submit" class="btn"><i class="fa-solid fa-paper-plane"></i></button>
        </form>
        {% else %}
        <div style="padding: 15px; color: var(--danger); text-align: center; font-weight: bold;">ДОСТУП К ЧАТУ ОГРАНИЧЕН (БАН ИЛИ МУТ)</div>
        {% endif %}
    </div>
    <script>
    const channel = "{{ channel }}";
    let isFirstLoad = true;

    async function fetchMessages() {
        try {
            const res = await fetch('/api/chat/' + channel + '/messages');
            if (!res.ok) return;
            const messages = await res.json();
            const container = document.getElementById('chatMessages');
            const isAtBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 80;
            
            container.innerHTML = messages.map(msg => `
                <div style="margin-bottom: 12px; padding: 12px 15px; background: rgba(0,0,0,0.4); border-left: 3px solid var(--primary); border-radius: 0 12px 12px 0;">
                    <a href="/profile/${msg.author_id}" style="color: var(--primary); font-weight: 700; text-decoration: none;">${msg.username}</a>
                    <span style="color: #a0aec0; font-size: 12px; margin-left: 10px;">${msg.timestamp}</span>
                    <div style="margin-top: 6px; font-size: 16px; color: #fff;">${msg.content}</div>
                </div>
            `).join('');
            
            if (isFirstLoad || isAtBottom) {
                container.scrollTop = container.scrollHeight;
                isFirstLoad = false;
            }
        } catch(e) {}
    }

    setInterval(fetchMessages, 2500);
    fetchMessages();

    const form = document.getElementById('chatForm');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const input = document.getElementById('chatInput');
            const text = input.value.trim();
            if (!text) return;
            
            const res = await fetch('/api/chat/' + channel + '/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({content: text})
            });
            if (res.ok) { input.value = ''; fetchMessages(); }
        });
    }
    </script>
    """
    return render_template_string(
        BASE_HTML.replace('{% block content %}{% endblock %}', content), 
        user=user, channel=channel, check_perm=check_perm,
        departments_keys=list(DEPARTMENTS.keys()), get_epaulette_svg=get_epaulette_svg,
        is_admin_access=is_admin_access, now=datetime.utcnow()
    )

@app.route('/api/chat/<channel>/messages')
@login_required
def api_chat_messages(channel):
    user = get_current_user()
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    if channel != "global" and channel != "news" and channel != user.department and not is_admin_access:
        return jsonify([]), 403
            
    messages = Message.query.filter_by(channel=channel).order_by(Message.timestamp.asc()).limit(100).all()
    return jsonify([{
        "id": m.id, "author_id": m.author_id, "username": m.author.username,
        "content": m.content, "timestamp": m.timestamp.strftime('%H:%M:%S')
    } for m in messages])

@app.route('/api/chat/<channel>/send', methods=['POST'])
@login_required
def api_chat_send(channel):
    user = get_current_user()
    if is_user_banned(user) or is_user_muted(user): return jsonify({"error": "Ограничение доступа."}), 403
    is_admin_access = user.admin_level != "Нет" or check_perm(user, 'can_view_apps') or check_perm(user, 'can_approve_apps')
    
    if channel != "global" and channel != "news" and channel != user.department and not is_admin_access:
        return jsonify({"error": "Нет доступа."}), 403
            
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    if not content: return jsonify({"error": "Пустое сообщение."}), 400
        
    msg = Message(channel=channel, author_id=user.id, content=content)
    db.session.add(msg)
    db.session.commit()
    return jsonify({"success": True})

# =======================
# АВТОРИЗАЦИЯ
# =======================
AUTH_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lordship Access</title>
    <link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;700&display=swap" rel="stylesheet">
    <style>
        body {
            margin: 0; padding: 15px; font-family: 'Rajdhani', sans-serif;
            background: linear-gradient(-45deg, #050b14, #0a1128, #000000, #0c0822);
            background-size: 400% 400%; animation: gradientBG 15s ease infinite;
            display: flex; justify-content: center; align-items: center; min-height: 100vh; color: #fff; box-sizing: border-box;
        }
        @keyframes gradientBG { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
        .box {
            background: rgba(13, 17, 28, 0.85); backdrop-filter: blur(20px);
            padding: 40px 30px; border-radius: 16px; border: 1px solid rgba(255,255,255,0.1);
            text-align: center; width: 100%; max-width: 400px; box-shadow: 0 15px 35px rgba(0,0,0,0.5);
        }
        h2 { color: #00f0ff; margin-bottom: 25px; font-size: 28px; letter-spacing: 3px; text-transform: uppercase; }
        input {
            width: 100%; padding: 14px; margin: 10px 0; background: rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.2); color: #fff; border-radius: 8px; font-size: 16px; box-sizing: border-box;
        }
        button {
            width: 100%; padding: 14px; background: linear-gradient(45deg, #0055ff, #00f0ff);
            border: none; color: #fff; cursor: pointer; border-radius: 8px; font-size: 17px; font-weight: bold; margin-top: 15px;
        }
        a { color: #a0aec0; text-decoration: none; display: block; margin-top: 20px; font-size: 15px; }
        .error { color: #ff0055; margin-bottom: 15px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="box">
        <h2>Lordship Network</h2>
        {% with messages = get_flashed_messages() %}{% if messages %}<div class="error">{{ messages[0] }}</div>{% endif %}{% endwith %}
        {{ form | safe }}
    </div>
</body>
</html>
"""

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        flash('ОТКАЗАНО В ДОСТУПЕ. Неверные данные.')
    
    form = """
    <form method="POST">
        <input type="text" name="username" placeholder="Идентификатор (Никнейм)" required>
        <input type="password" name="password" placeholder="Ключ доступа (Пароль)" required>
        <button type="submit">АВТОРИЗАЦИЯ</button>
    </form>
    <a href="/register">ЗАПРОСИТЬ ДОСТУП (РЕГИСТРАЦИЯ)</a>
    """
    return render_template_string(AUTH_HTML, form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        age = request.form.get('age')
        
        if User.query.filter_by(username=username).first():
            flash('ОШИБКА БАЗЫ: Никнейм уже занят')
            return redirect(url_for('register'))
            
        is_first = User.query.count() == 0
        new_user = User(
            username=username, 
            password_hash=generate_password_hash(password),
            age=int(age),
            rank="владелец" if is_first else "Стажер",
            admin_level="Специальный Администратор" if is_first else "Нет"
        )
        db.session.add(new_user)
        db.session.commit()
        log_history(new_user.id, "Учетная запись создана.")
        return redirect(url_for('login'))
        
    form = """
    <form method="POST">
        <input type="text" name="username" placeholder="Игровой Никнейм" required>
        <input type="number" name="age" placeholder="Возраст (ООС)" required>
        <input type="password" name="password" placeholder="Пароль" required>
        <button type="submit">ИНИЦИАЛИЗАЦИЯ</button>
    </form>
    <a href="/login">ВЕРНУТЬСЯ К ВХОДУ</a>
    """
    return render_template_string(AUTH_HTML, form=form)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# =======================
# ИНИЦИАЛИЗАЦИЯ ПРИ СТАРТЕ WSGI (СОВМЕСТИМО С POSTGRESQL)
# =======================
with app.app_context():
    db.create_all()
    with db.engine.connect() as conn:
        for tbl, col in [
            ('user', 'warn_reset_flag BOOLEAN DEFAULT FALSE'),
            ('user', 'warn_reset_time TIMESTAMP'),
            ('role_permission', 'can_delete_all_news BOOLEAN DEFAULT FALSE'),
            ('user_permission_override', 'can_delete_all_news BOOLEAN DEFAULT FALSE')
        ]:
            try:
                conn.execute(db.text(f'ALTER TABLE "{tbl}" ADD COLUMN IF NOT EXISTS {col}'))
            except Exception:
                pass
        conn.commit()
    init_permissions()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
