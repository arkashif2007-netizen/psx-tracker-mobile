import json
import os
import sqlite3
import time
import threading
from datetime import datetime


from flask import Flask, render_template, jsonify, request, make_response

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'data.db')
SYMBOLS_CACHE = os.path.join(BASE_DIR, 'static', 'symbols_tv.json')
PRICE_REFRESH_SECONDS = 10**9
INDIVIDUALS = ['kashif', 'shahvez']

# Symbol catalog
SYMBOL_CATALOG = []

# Price cache
_price_cache = {}
_price_lock = threading.Lock()
_last_price_refresh = None


# ---------------- DB helpers ----------------
def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def query_db(sql, args=(), one=False):
    with get_db() as conn:
        cur = conn.execute(sql, args)
        rows = cur.fetchall()
    return (dict(rows[0]) if rows else None) if one else [dict(r) for r in rows]


def write_db(sql, args=()):
    with get_db() as conn:
        conn.execute(sql, args)
        conn.commit()


def init_db():
    schema = """
    CREATE TABLE IF NOT EXISTS individuals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        total_invested REAL NOT NULL DEFAULT 0,
        total_withdrawn REAL NOT NULL DEFAULT 0,
        available_balance REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS holdings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        individual TEXT NOT NULL,
        symbol TEXT NOT NULL,
        stock_name TEXT,
        quantity REAL NOT NULL,
        avg_cost REAL NOT NULL,
        total_cost REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        individual TEXT NOT NULL,
        type TEXT NOT NULL,
        symbol TEXT,
        stock_name TEXT,
        quantity REAL,
        price REAL,
        fees REAL DEFAULT 0,
        brokerage REAL DEFAULT 0,
        total_value REAL NOT NULL,
        date TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tax_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        individual TEXT NOT NULL,
        amount REAL NOT NULL,
        period TEXT,
        date TEXT,
        note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS symbol_watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        individual TEXT NOT NULL,
        symbol TEXT NOT NULL,
        high REAL,
        low REAL,
        prev_close REAL,
        updated_at TEXT
    );
    """
    with get_db() as conn:
        conn.executescript(schema)
    for ind in INDIVIDUALS:
        write_db(
            "INSERT OR IGNORE INTO individuals (name, total_invested, total_withdrawn, available_balance) VALUES (?,?,?,?)",
            (ind, 0.0, 0.0, 0.0),
        )


# ---------------- Catalog from TradingView ----------------
def load_symbol_catalog():
    global SYMBOL_CATALOG
    try:
        with open(SYMBOLS_CACHE, 'r', encoding='utf-8') as f:
            SYMBOL_CATALOG = json.load(f)
    except Exception:
        SYMBOL_CATALOG = []
    return SYMBOL_CATALOG


# ---------------- Price fetch ----------------
_TV_SCAN_URL = "https://scanner.tradingview.com/pakistan/scan"


def _tv_scan_raw():
    req = Request(_TV_SCAN_URL, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_psx_quote(symbol: str):
    """Best-effort public PSX quote fallback."""
    try:
        url = f"https://dps.psx.com.pk/quote/{symbol}"
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8", errors="ignore")
        import re
        m = re.search(r'"last[_-]?price"\s*:\s*([0-9]+\.[0-9]+)', data)
        if not m:
            m = re.search(r'([0-9]+\\.[0-9]+)\\s*PKR', data)
        if m:
            return round(float(m.group(1)), 2)
    except Exception:
        pass
    return None


def get_cached_prices(symbols):
    global _last_price_refresh, _price_cache
    now = time.time()
    if _last_price_refresh is None or now - _last_price_refresh > PRICE_REFRESH_SECONDS:
        with _price_lock:
            if _last_price_refresh is None or now - _last_price_refresh > PRICE_REFRESH_SECONDS:
                try:
                    fresh = {}
                    raw = _tv_scan_raw() or {}
                    data = raw.get("data") or []
                    for item in data:
                        s = (item.get("s") or "").replace("PSX:", "").strip()
                        d = item.get("d") or {}
                        close = d.get("close")
                        if s and close is not None:
                            try:
                                fresh[s] = {"price": round(float(close), 2)}
                            except (TypeError, ValueError):
                                pass
                    # Fill missing symbols with public PSX fallback
                    for s in symbols:
                        if s not in fresh:
                            p = _fetch_psx_quote(s)
                            if p is not None:
                                fresh[s] = {"price": p}
                    _price_cache = fresh
                    _last_price_refresh = now
                except Exception as e:
                    print("[PRICE] refresh failed:", e)
                    _last_price_refresh = now
    return {s: _price_cache.get(s, {"price": 0.0}) for s in symbols}


# ---------------- Summary ----------------
def get_individual_summary(individual: str):
    ind = query_db("SELECT * FROM individuals WHERE name=?", (individual,), one=True) or {
        'name': individual,
        'total_invested': 0.0,
        'total_withdrawn': 0.0,
        'available_balance': 0.0,
    }
    holdings = query_db("SELECT * FROM holdings WHERE individual=?", (individual,))
    tax_paid = query_db("SELECT SUM(amount) as s FROM tax_payments WHERE individual=?", (individual,), one=True)
    tax_paid = float(tax_paid['s'] or 0)

    buys = query_db("SELECT total_value FROM transactions WHERE individual=? AND type='buy'", (individual,))
    sells = query_db("SELECT total_value FROM transactions WHERE individual=? AND type='sell'", (individual,))
    invested = sum(float(r['total_value'] or 0) for r in buys)
    realized = sum(float(r['total_value'] or 0) for r in sells) - invested

    hold_rows = []
    for h in holdings:
        hold_rows.append({
            'id': h['id'],
            'symbol': h['symbol'],
            'stock_name': h.get('stock_name') or h['symbol'],
            'quantity': float(h['quantity'] or 0),
            'avg_cost': float(h['avg_cost'] or 0),
            'total_cost': float(h['total_cost'] or 0),
            'live_price': 0.0,
            'unrealized_pnl': 0.0,
            'unrealized_pct': 0.0,
            'net_unrealized_pnl': 0.0,
            'buy_tax_rate': 0.15,
        })

    return {
        'name': individual,
        'initial_capital': float(ind.get('available_balance') or 0),
        'current_balance': float(ind.get('available_balance') or 0),
        'total_invested': round(invested, 2),
        'total_withdrawn': float(ind.get('total_withdrawn') or 0),
        'realized_profit': round(realized, 2),
        'tax_owed': round(max(0, realized * 0.15), 2),
        'tax_paid': round(tax_paid, 2),
        'holdings': hold_rows,
    }


def _summary_with_prices(individual: str):
    summary = get_individual_summary(individual)
    symbols = [h['symbol'] for h in summary['holdings']]
    prices = get_cached_prices(symbols)
    for h in summary['holdings']:
        p = prices.get(h['symbol'], {}).get('price')
        if p:
            live = float(p)
            avg = float(h['avg_cost'])
            qty = float(h['quantity'])
            h['live_price'] = live
            h['unrealized_pnl'] = round((live - avg) * qty, 2)
            h['unrealized_pct'] = round(((live - avg) / avg) * 100 if avg else 0.0, 2)
            h['net_unrealized_pnl'] = round(h['unrealized_pnl'] * (1 - 0.15), 2)
    return summary


# ---------------- Routes ----------------
@app.route('/')
def index():
    k = _summary_with_prices('kashif')
    s = _summary_with_prices('shahvez')

    total_invested = round(k['total_invested'] + s['total_invested'], 2)
    total_withdrawn = round(k['total_withdrawn'] + s['total_withdrawn'], 2)
    portfolio_value = round(k['current_balance'] + s['current_balance'] + k['total_invested'] + s['total_invested'], 2)
    net_realized = round(k['realized_profit'] + s['realized_profit'], 2)

    def user_unr(u):
        unr = sum(h.get('unrealized_pnl', 0) for h in u['holdings'])
        buy_tax = round(abs(unr) * 0.15, 2)
        net = round(unr - buy_tax, 2)
        return unr, buy_tax, net

    ku, kb, kn = user_unr(k)
    su, sb, sn = user_unr(s)

    return render_template(
        'index.html',
        kashif=k,
        shahvez=s,
        total_invested=total_invested,
        total_withdrawn=total_withdrawn,
        portfolio_value=portfolio_value,
        net_realized=net_realized,
        combined_unrealized=round(ku + su, 2),
        combined_buy_tax=round(kb + sb, 2),
        combined_net_unrealized=round(kn + sn, 2),
        tax_owed=round(k['tax_owed'] + s['tax_owed'], 2),
        tax_paid=round(k['tax_paid'] + s['tax_paid'], 2),
        tax_payable=round(max(0, (k['tax_owed'] + s['tax_owed']) - (k['tax_paid'] + s['tax_paid'])), 2),
        now=datetime.now(),
    )


@app.route('/api/dashboard', methods=['GET'])
def api_dashboard():
    k = _summary_with_prices('kashif')
    s = _summary_with_prices('shahvez')
    symbols = list({h['symbol'] for h in k['holdings'] + s['holdings']})
    prices = get_cached_prices(symbols)
    return jsonify({'status': 'ok', 'kashif': k, 'shahvez': s, 'prices': prices})


@app.route('/api/symbols', methods=['GET'])
def api_symbols():
    catalog = load_symbol_catalog()
    return jsonify({
        'status': 'ok',
        'symbols': [{'symbol': x['symbol'], 'name': x['name'], 'sector': x['sector']} for x in catalog],
        'count': len(catalog),
    })


@app.route('/api/price/<symbol>')
def api_price(symbol):
    p = get_cached_prices([symbol.upper()]).get(symbol.upper(), {}).get('price')
    return jsonify({'status': 'ok', 'symbol': symbol.upper(), 'price': p})


@app.route('/api/holdings/<individual>', methods=['GET'])
def api_holdings(individual):
    rows = query_db("SELECT * FROM holdings WHERE individual=?", (individual,))
    return jsonify({'status': 'ok', 'holdings': rows})


@app.route('/api/transactions', methods=['GET'])
def api_list_transactions():
    individual = request.args.get('individual', 'kashif')
    rows = query_db("SELECT * FROM transactions WHERE individual=? ORDER BY date DESC", (individual,))
    return jsonify({'status': 'ok', 'transactions': rows})


@app.route('/api/transactions', methods=['POST'])
def api_add_transaction():
    data = request.get_json(force=True)
    individual = data.get('individual')
    ttype = data.get('type')
    symbol = data.get('symbol', '').upper()
    stock_name = data.get('stock_name', symbol)
    quantity = float(data.get('quantity') or 0)
    price = float(data.get('price') or 0)
    fees = float(data.get('fees') or 0)
    brokerage = float(data.get('brokerage') or 0)
    total_value = float(data.get('total_value') or (price * quantity + fees + brokerage))
    notes = data.get('notes', '')
    date = data.get('date') or today_iso()
    if not individual or not ttype or total_value == 0:
        return jsonify({'status': 'error', 'error': 'individual, type and total_value required'}), 400

    with get_db() as conn:
        conn.execute(
            """INSERT INTO transactions (individual, type, symbol, stock_name, quantity, price, fees, brokerage, total_value, date, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (individual, ttype, symbol, stock_name, quantity, price, fees, brokerage, total_value, date, notes),
        )
        if ttype == 'buy':
            # Upsert holding
            row = conn.execute("SELECT * FROM holdings WHERE individual=? AND symbol=?", (individual, symbol)).fetchone()
            if row:
                new_qty = float(row['quantity']) + quantity
                new_total = float(row['total_cost']) + total_value
                new_avg = new_total / new_qty if new_qty else 0
                conn.execute(
                    "UPDATE holdings SET quantity=?, avg_cost=?, total_cost=?, stock_name=? WHERE id=?",
                    (new_qty, new_avg, new_total, stock_name or symbol, row['id']),
                )
            else:
                conn.execute(
                    "INSERT INTO holdings (individual, symbol, stock_name, quantity, avg_cost, total_cost) VALUES (?,?,?,?,?,?)",
                    (individual, symbol, stock_name or symbol, quantity, (total_value / quantity) if quantity else 0, total_value),
                )
            conn.execute("UPDATE individuals SET total_invested=total_invested+?, available_balance=available_balance-? WHERE name=?", (total_value, total_value, individual))
        elif ttype == 'sell':
            conn.execute("UPDATE individuals SET available_balance=available_balance+? WHERE name=?", (total_value, individual))
            row = conn.execute("SELECT * FROM holdings WHERE individual=? AND symbol=?", (individual, symbol)).fetchone()
            if row:
                new_qty = float(row['quantity']) - quantity
                if new_qty <= 0.001:
                    conn.execute("DELETE FROM holdings WHERE id=?", (row['id'],))
                else:
                    conn.execute("UPDATE holdings SET quantity=? WHERE id=?", (new_qty, row['id']))
        elif ttype in ('capital_add',):
            conn.execute("UPDATE individuals SET available_balance=available_balance+?, total_invested=total_invested+? WHERE name=?", (total_value, total_value, individual))
        elif ttype in ('capital_withdraw',):
            conn.execute("UPDATE individuals SET available_balance=available_balance-?, total_withdrawn=total_withdrawn+? WHERE name=?", (total_value, total_value, individual))
        elif ttype == 'tax_payment':
            conn.execute("INSERT INTO tax_payments (individual, amount, period, date, note) VALUES (?,?,?,?,?)", (individual, total_value, notes, date, 'Tax payment'))
    return jsonify({'status': 'ok'})


@app.route('/api/capital', methods=['POST'])
def api_capital():
    data = request.get_json(force=True)
    individual = data.get('individual')
    amount = float(data.get('amount') or 0)
    ctype = data.get('ctype')
    if not individual or not ctype or amount == 0:
        return jsonify({'status': 'error', 'error': 'individual, ctype, amount required'}), 400
    with get_db() as conn:
        if ctype == 'add':
            conn.execute("UPDATE individuals SET available_balance=available_balance+?, total_invested=total_invested+? WHERE name=?", (amount, amount, individual))
        else:
            conn.execute("UPDATE individuals SET available_balance=available_balance-?, total_withdrawn=total_withdrawn+? WHERE name=?", (amount, amount, individual))
        ttype = 'capital_add' if ctype == 'add' else 'capital_withdraw'
        conn.execute("INSERT INTO transactions (individual, type, total_value, notes) VALUES (?,?,?,?)", (individual, ttype, amount, ctype))
    return jsonify({'status': 'ok'})


@app.route('/api/tax', methods=['POST'])
def api_tax():
    data = request.get_json(force=True)
    individual = data.get('individual')
    amount = float(data.get('amount') or 0)
    if not individual or amount <= 0:
        return jsonify({'status': 'error', 'error': 'invalid request'}), 400
    with get_db() as conn:
        conn.execute("INSERT INTO tax_payments (individual, amount, period, date, note) VALUES (?,?,?,?,?)", (individual, amount, '', today_iso(), 'Tax payment'))
    return jsonify({'status': 'ok'})


@app.route('/api/audit-log/<individual>')
def api_audit(individual):
    rows = query_db("SELECT * FROM transactions WHERE individual=? ORDER BY date DESC", (individual,))
    return jsonify({'status': 'ok', 'audit': rows})


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})



@app.route('/api/transactions/<individual>', methods=['GET'])
def api_user_transactions(individual):
    if individual not in ('kashif', 'shahvez'):
        return jsonify({'status':'error','error':'invalid individual'}), 400
    rows = query_db("SELECT * FROM transactions WHERE individual=? ORDER BY date DESC", (individual,))
    return jsonify({'status':'ok','transactions':rows})

@app.route('/api/holdings/<individual>', methods=['GET'])
def api_user_holdings(individual):
    if individual not in ('kashif', 'shahvez'):
        return jsonify({'status':'error','error':'invalid individual'}), 400
    rows = query_db("SELECT * FROM holdings WHERE individual=?", (individual,))
    return jsonify({'status':'ok','holdings':rows})


@app.route('/mobile')
def mobile():
    return render_template('mobile.html')


if __name__ == '__main__':
    init_db()
    load_symbol_catalog()
    app.run(host='0.0.0.0', port=5000, debug=False)
    init_db()
    load_symbol_catalog()
    app.run(host='0.0.0.0', port=5000, debug=False)


@app.after_request
def allow_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp
