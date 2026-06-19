# PSX Tracker — Database Layer
# Uses psx-tradingview-integration skill DB schema + business rules

import sqlite3
import os
from datetime import datetime

from config import DATABASE, TAX_RATE


def db_get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_database() -> None:
    conn = db_get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS individuals (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            total_invested REAL DEFAULT 0,
            total_withdrawn REAL DEFAULT 0,
            available_balance REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS capital_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual TEXT NOT NULL,
            type TEXT NOT NULL,           -- 'deposit' | 'withdrawal'
            amount REAL NOT NULL,
            note TEXT,
            date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual TEXT NOT NULL,
            type TEXT NOT NULL,           -- 'buy' | 'sell'
            symbol TEXT NOT NULL,
            stock_name TEXT,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            fees REAL DEFAULT 0,
            brokerage REAL DEFAULT 0,
            total_value REAL NOT NULL,    -- qty * price + fees + brokerage
            date TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual TEXT NOT NULL,
            symbol TEXT NOT NULL,
            stock_name TEXT,
            quantity REAL NOT NULL DEFAULT 0,
            avg_cost REAL NOT NULL DEFAULT 0,    -- weighted avg cost basis
            total_cost REAL NOT NULL DEFAULT 0,
            UNIQUE(individual, symbol)
        );

        CREATE TABLE IF NOT EXISTS realized_profits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual TEXT NOT NULL,
            symbol TEXT NOT NULL,
            sell_date TEXT NOT NULL,
            quantity REAL NOT NULL,
            cost_basis REAL NOT NULL,
            sell_price REAL NOT NULL,
            gross_profit REAL NOT NULL,
            tax_rate REAL NOT NULL,
            tax_owed REAL NOT NULL,
            net_profit REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tax_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual TEXT NOT NULL,
            amount REAL NOT NULL,
            period TEXT,
            date TEXT NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            individual TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_transactions_individual
            ON transactions(individual);
        CREATE INDEX IF NOT EXISTS idx_holdings_individual
            ON holdings(individual);
        CREATE INDEX IF NOT EXISTS idx_realized_individual
            ON realized_profits(individual);
        CREATE INDEX IF NOT EXISTS idx_audit_individual
            ON audit_log(individual);
    """)
    conn.commit()
    conn.close()


def init_individuals() -> None:
    conn = db_get_db()
    cur = conn.cursor()
    for name in ['kashif', 'shahvez']:
        cur.execute(
            "INSERT OR IGNORE INTO individuals (name, available_balance) VALUES (?, 0)",
            (name,),
        )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _audit(conn: sqlite3.Connection, individual: str, action: str, details: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_log (individual, action, details) VALUES (?, ?, ?)",
        (individual, action, details),
    )


def _get_available_balance(conn: sqlite3.Connection, individual: str) -> float:
    row = conn.execute(
        "SELECT available_balance FROM individuals WHERE name=?",
        (individual,),
    ).fetchone()
    if not row:
        raise ValueError(f"Unknown individual: {individual}")
    return float(row['available_balance'])


def _set_available_balance(conn: sqlite3.Connection, individual: str, value: float) -> float:
    conn.execute(
        "UPDATE individuals SET available_balance=? WHERE name=?",
        (value, individual),
    )
    conn.commit()
    row = conn.execute(
        "SELECT available_balance FROM individuals WHERE name=?",
        (individual,),
    ).fetchone()
    return float(row['available_balance'])


# ------------------------------------------------------------------
# Capital (deposit / withdrawal)
# ------------------------------------------------------------------
def db_add_capital(individual: str, cap_type: str, amount: float, date: str, note: str = "") -> dict:
    if individual not in ('kashif', 'shahvez'):
        raise ValueError("individual must be 'kashif' or 'shahvez'")
    if amount <= 0:
        raise ValueError("amount must be > 0")

    conn = db_get_db()
    try:
        available = _get_available_balance(conn, individual)
        if cap_type == 'withdrawal' and available < amount:
            raise ValueError("Insufficient available balance")

        conn.execute(
            "INSERT INTO capital_entries (individual, type, amount, note, date) VALUES (?, ?, ?, ?, ?)",
            (individual, cap_type, amount, note, date),
        )

        if cap_type == 'deposit':
            conn.execute(
                "UPDATE individuals SET total_invested = total_invested + ?, available_balance = available_balance + ? WHERE name=?",
                (amount, amount, individual),
            )
        else:
            conn.execute(
                "UPDATE individuals SET total_withdrawn = total_withdrawn + ?, available_balance = available_balance - ? WHERE name=?",
                (amount, amount, individual),
            )
        _audit(conn, individual, cap_type, f"amount={amount}")
        conn.commit()
        new_balance = _get_available_balance(conn, individual)
        return {"status": "ok", "new_balance": new_balance}
    finally:
        conn.close()


# ------------------------------------------------------------------
# Transactions (buy / sell)
# ------------------------------------------------------------------
def _update_holdings_on_buy(
    conn: sqlite3.Connection, individual: str, symbol: str, stock_name: str, quantity: float, price: float, fees: float, brokerage: float
) -> dict:
    new_cost = price * quantity + fees + brokerage
    existing = conn.execute(
        "SELECT quantity, avg_cost, total_cost FROM holdings WHERE individual=? AND symbol=?",
        (individual, symbol),
    ).fetchone()

    if existing:
        total_qty = existing['quantity'] + quantity
        total_cost = existing['total_cost'] + new_cost
        avg_cost = total_cost / total_qty
        conn.execute(
            "UPDATE holdings SET quantity=?, avg_cost=?, total_cost=?, stock_name=? WHERE individual=? AND symbol=?",
            (total_qty, avg_cost, total_cost, stock_name, individual, symbol),
        )
    else:
        avg_cost = new_cost / quantity
        conn.execute(
            "INSERT INTO holdings (individual, symbol, stock_name, quantity, avg_cost, total_cost) VALUES (?, ?, ?, ?, ?, ?)",
            (individual, symbol, stock_name, quantity, avg_cost, new_cost),
        )
    return {"status": "ok"}


def db_add_transaction(data: dict) -> dict:
    """
    Handles both BUY and SELL with full business rules.
    - On BUY: insert transaction, update holdings (weighted avg), deduct balance
    - On SELL: validate holdings, compute realized profit, insert tx +
               realized_profits, reduce/remove holdings, add proceeds to balance
               (tax stays owed, not auto-paid)
    """
    required = ['individual', 'type', 'symbol', 'quantity', 'price', 'date']
    for k in required:
        if k not in data:
            raise ValueError(f"missing required field: {k}")

    individual = data['individual']
    tx_type    = data['type']
    symbol     = data['symbol'].upper()
    stock_name = data.get('stock_name', '')
    quantity   = float(data['quantity'])
    price      = float(data['price'])
    fees       = float(data.get('fees', 0))
    brokerage  = float(data.get('brokerage', 0))
    date       = data['date']
    notes      = data.get('notes', '')
    total_value = round(quantity * price + fees + brokerage, 2)

    conn = db_get_db()
    try:
        if tx_type == 'buy':
            available = _get_available_balance(conn, individual)
            if available < total_value:
                raise ValueError("Insufficient available balance to buy")

            # Deduct purchase cost from available balance
            _set_available_balance(conn, individual, available - total_value)

            # Record transaction
            conn.execute(
                "INSERT INTO transactions (individual, type, symbol, stock_name, quantity, price, fees, brokerage, total_value, date, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (individual, tx_type, symbol, stock_name, quantity, price, fees, brokerage, total_value, date, notes),
            )

            # Update holdings (weighted avg cost)
            _update_holdings_on_buy(conn, individual, symbol, stock_name, quantity, price, fees, brokerage)

            _audit(conn, individual, 'buy', f"{symbol} qty={quantity} price={price} total={total_value}")
            conn.commit()
            return {"status": "ok", "new_balance": _get_available_balance(conn, individual)}

        elif tx_type == 'sell':
            holding = conn.execute(
                "SELECT quantity, avg_cost, total_cost FROM holdings WHERE individual=? AND symbol=?",
                (individual, symbol),
            ).fetchone()
            if not holding or holding['quantity'] < quantity:
                raise ValueError("Insufficient holdings for sell")

            # Realized profit using FIFO-style avg cost
            cost_basis = holding['avg_cost'] * quantity
            sell_value = (price * quantity) - fees
            gross_profit = sell_value - cost_basis
            tax_owed = max(0, gross_profit * TAX_RATE)
            net_profit = gross_profit - tax_owed

            # Record transaction
            conn.execute(
                "INSERT INTO transactions (individual, type, symbol, stock_name, quantity, price, fees, brokerage, total_value, date, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (individual, tx_type, symbol, stock_name, quantity, price, fees, brokerage, sell_value, date, notes),
            )

            # Record realized profit
            conn.execute(
                "INSERT INTO realized_profits (individual, symbol, sell_date, quantity, cost_basis, sell_price, gross_profit, tax_rate, tax_owed, net_profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (individual, symbol, date, quantity, cost_basis, price, gross_profit, TAX_RATE, tax_owed, net_profit),
            )

            # Update holdings
            new_qty = holding['quantity'] - quantity
            avg_cost = float(holding['avg_cost'])
            total_cost = avg_cost * new_qty

            if new_qty <= 0:
                conn.execute("DELETE FROM holdings WHERE individual=? AND symbol=?", (individual, symbol))
            else:
                conn.execute(
                    "UPDATE holdings SET quantity=?, total_cost=? WHERE individual=? AND symbol=?",
                    (new_qty, total_cost, individual, symbol),
                )

            # Add proceeds to available balance (tax stays owed)
            _set_available_balance(conn, individual, _get_available_balance(conn, individual) + sell_value)

            _audit(conn, individual, 'sell', f"{symbol} qty={quantity} net_profit={net_profit}")
            conn.commit()
            return {
                "status": "ok",
                "realized_profit": {
                    "gross_profit": round(gross_profit, 2),
                    "tax_owed": round(tax_owed, 2),
                    "net_profit": round(net_profit, 2),
                    "tax_rate": TAX_RATE,
                },
                "new_balance": _get_available_balance(conn, individual),
            }
        else:
            raise ValueError(f"Unknown transaction type: {tx_type}")
    finally:
        conn.close()


# ------------------------------------------------------------------
# Tax Payments
# ------------------------------------------------------------------
def db_record_tax_payment(individual: str, amount: float, date: str, period: str = "", note: str = "") -> dict:
    if individual not in ('kashif', 'shahvez'):
        raise ValueError("individual must be 'kashif' or 'shahvez'")
    if amount <= 0:
        raise ValueError("amount must be > 0")

    conn = db_get_db()
    try:
        available = _get_available_balance(conn, individual)
        if available < amount:
            raise ValueError("Insufficient available balance to pay tax")

        conn.execute(
            "INSERT INTO tax_payments (individual, amount, period, date, note) VALUES (?, ?, ?, ?, ?)",
            (individual, amount, period, date, note),
        )
        _set_available_balance(conn, individual, available - amount)
        _audit(conn, individual, 'tax_payment', f"amount={amount} period={period}")
        conn.commit()
        return {"status": "ok", "new_balance": _get_available_balance(conn, individual)}
    finally:
        conn.close()


# ------------------------------------------------------------------
# Summary / Holdings / History queries
# ------------------------------------------------------------------
def db_get_individual_summary(individual: str) -> dict:
    conn = db_get_db()
    try:
        profile = conn.execute(
            "SELECT name, total_invested, total_withdrawn, available_balance FROM individuals WHERE name=?",
            (individual,),
        ).fetchone()
        if not profile:
            raise ValueError(f"Unknown individual: {individual}")

        holdings = db_get_holdings(individual)
        transactions = db_get_transactions(individual, limit=20)

        tax_owed_row = conn.execute(
            "SELECT COALESCE(SUM(tax_owed), 0) AS tax_owed FROM realized_profits WHERE individual=?",
            (individual,),
        ).fetchone()
        tax_paid_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS tax_paid FROM tax_payments WHERE individual=?",
            (individual,),
        ).fetchone()
        tax_owed = float(tax_owed_row['tax_owed'] or 0)
        tax_paid = float(tax_paid_row['tax_paid'] or 0)
        gross_row = conn.execute(
            "SELECT COALESCE(SUM(gross_profit),0) AS gross_profit FROM realized_profits WHERE individual=?",
            (individual,),
        ).fetchone()
        realized_profit = float(gross_row['gross_profit'] or 0)

        total_cost = 0.0
        market_value = 0.0
        for h in holdings:
            cost = float(h.get('total_cost', 0) or 0)
            qty = float(h.get('quantity', 0) or 0)
            price = float(h.get('live_price', 0) or 0)
            total_cost += cost
            market_value += qty * price

        unrealized_pnl = round(market_value - total_cost, 2)
        unrealized_pct = round(((market_value - total_cost) / total_cost * 100) if total_cost else 0.0, 2)
        buy_tax = round(total_cost * TAX_RATE, 2)
        tax_payable = max(0.0, round(tax_owed - tax_paid, 2))
        net_unrealized_pnl = round(unrealized_pnl - buy_tax, 2)

        summary = dict(profile)
        summary.update({
            'holdings': holdings,
            'recent_transactions': transactions,
            'realized_profit': realized_profit,
            'tax_owed': tax_owed,
            'tax_paid': tax_paid,
            'tax_payable': tax_payable,
            'buy_tax': buy_tax,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pct': unrealized_pct,
            'net_unrealized_pnl': net_unrealized_pnl,
            'net_position': summary['available_balance'] + total_cost,
            'total_cost': total_cost,
            'market_value': market_value,
            'total_tax_paid': tax_paid,
            'price_updated_at': datetime.now().isoformat(),
        })
        return summary
    finally:
        conn.close()

def db_get_holdings(individual: str) -> list[dict]:
    conn = db_get_db()
    try:
        rows = conn.execute(
            "SELECT symbol, stock_name, quantity, avg_cost, total_cost FROM holdings WHERE individual=?",
            (individual,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def db_get_transactions(individual: str, limit: int = 50) -> list[dict]:
    conn = db_get_db()
    try:
        rows = conn.execute(
            "SELECT id, type, symbol, stock_name, quantity, price, fees, brokerage, total_value, date, notes, created_at "
            "FROM transactions WHERE individual=? ORDER BY datetime(date) DESC LIMIT ?",
            (individual, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def db_get_audit_log(individual: str, limit: int = 100) -> list[dict]:
    conn = db_get_db()
    try:
        rows = conn.execute(
            "SELECT id, action, details, timestamp FROM audit_log WHERE individual=? ORDER BY datetime(timestamp) DESC LIMIT ?",
            (individual, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ------------------------------------------------------------------
# Direct test runner
# ------------------------------------------------------------------
if __name__ == '__main__':
    init_database()
    init_individuals()
    print("Initialized DB:", DATABASE)
    conn = db_get_db()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print("Tables:", tables)
    conn.close()
