from pathlib import Path

p = Path(r'C:\Users\ABDUL REHMAN\psx-tracker\database.py')
text = p.read_text(encoding='utf-8')

start = "def db_get_individual_summary(individual: str) -> dict:"
end = "\ndef db_get_holdings(individual: str) -> list[dict]:"

start_idx = text.index(start)
end_idx = text.index(end, start_idx)

new_body = '''def db_get_individual_summary(individual: str) -> dict:
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
'''

text = text[:start_idx] + new_body + text[end_idx:]
p.write_text(text, encoding='utf-8')
print('patched')
