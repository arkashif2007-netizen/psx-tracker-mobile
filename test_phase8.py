import sqlite3
from datetime import datetime

DB_PATH = r'C:\Users\ABDUL REHMAN\psx-tracker\data.db'

def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Verify initial state
    individuals = conn.execute("SELECT * FROM individuals").fetchall()
    print("\n=== Initial Individuals ===")
    for i in individuals:
        print(dict(i))
    
    # Insert capital deposit for Kashif
    print("\n=== Inserting Capital Deposit for Kashif ===")
    conn.execute("""
        INSERT INTO capital_entries (individual, type, amount, date, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ('kashif', 'deposit', 500000, '2024-01-01', 'Initial deposits', datetime.now().isoformat()))
    
    # Update individual balances
    conn.execute("""
        UPDATE individuals SET available_balance = available_balance + 500000 WHERE name = 'kashif'
    """)
    
    # Insert transaction for ENGRO buy
    print("=== Inserting ENGRO Buy Transaction ===")
    conn.execute("""
        INSERT INTO transactions (individual, type, symbol, stock_name, quantity, price, fees, brokerage, total_value, date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ('kashif', 'buy', 'ENGRO', 'Engro Corporation', 100, 250, 500, 250, 25000, '2024-01-02', 'Initial ENGRO buy'))
    
    # Update holdings (weighted average cost)
    conn.execute("""
        INSERT INTO holdings (individual, symbol, stock_name, quantity, avg_cost, total_cost)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(individual, symbol) DO UPDATE SET
            quantity = quantity + excluded.quantity,
            total_cost = total_cost + excluded.total_cost,
            avg_cost = (holdings.total_cost + excluded.total_cost) / (holdings.quantity + excluded.quantity)
    """, ('kashif', 'ENGRO', 'Engro Corporation', 100, 250.0 * 100 + 750, 25000))
    
    # Verify holdings
    holdings = conn.execute("SELECT * FROM holdings").fetchall()
    print("\n=== Current Holdings ===")
    for h in holdings:
        print(dict(h))
    
    # Verify audit log
    logs = conn.execute("SELECT * FROM audit_log").fetchall()
    print("\n=== Audit Log ===")
    for log in logs:
        print(dict(log))
    
    conn.commit()
    conn.close()
    
    print("\n✅ Test data inserted successfully")

run()
