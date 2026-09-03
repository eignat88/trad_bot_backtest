"""Quick baseline analysis for a single run."""
from __future__ import annotations
import os
from pg8000 import dbapi

def main():
    import sys
    run_id = sys.argv[1] if len(sys.argv) > 1 else "a802b387-6c50-425b-a350-3aca493e5aa6"
    conn = dbapi.connect(user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
                         host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
                         database=os.getenv("PGDATABASE", "trad_bot_backtest"))
    cur = conn.cursor()

    # By symbol
    cur.execute("""
        SELECT s.symbol,
               COUNT(*) as setups,
               SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) as entries,
               SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END) as tps,
               SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END) as sls,
               SUM(CASE WHEN o.first_event LIKE 'EXPIRED' THEN 1 ELSE 0 END) as expired,
               ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4) as avg_r_entry,
               ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 2) as total_r_entries,
               ROUND(AVG(o.result_r)::numeric, 4) as avg_r_all,
               ROUND(SUM(o.result_r)::numeric, 2) as total_r_all
        FROM bt.run r
        JOIN bt.setup s ON s.run_id = r.id
        JOIN bt.outcome o ON o.setup_id = s.id
        WHERE r.id = %s
        GROUP BY s.symbol ORDER BY total_r_all ASC
    """, (run_id,))
    print("=== BY SYMBOL ===")
    hdr = f"{'Symbol':<16} {'Set':>5} {'Ent':>5} {'TP':>4} {'SL':>4} {'Exp':>4} {'AvgR':>8} {'TotR':>10}"
    print(hdr)
    for r in cur.fetchall():
        print(f"{r[0]:<16} {r[1]:>5} {r[2]:>5} {r[3]:>4} {r[4]:>4} {r[5]:>4} {r[6] if r[6] else 0:>8} {r[9] if r[9] else 0:>10}")

    # By regime
    cur.execute("""
        SELECT s.regime, COUNT(*),
               SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
               SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END),
               ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
               ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 2)
        FROM bt.run r JOIN bt.setup s ON s.run_id = r.id JOIN bt.outcome o ON o.setup_id = s.id
        WHERE r.id = %s GROUP BY s.regime ORDER BY 6 ASC
    """, (run_id,))
    print("\n=== BY REGIME ===")
    print(f"{'Regime':<20} {'Set':>5} {'Ent':>5} {'Win':>4} {'AvgR':>8} {'TotR':>10}")
    for r in cur.fetchall():
        print(f"{r[0] or 'N/A':<20} {r[1]:>5} {r[2]:>5} {r[3]:>4} {r[4] if r[4] else 0:>8} {r[5] if r[5] else 0:>10}")

    # By event
    cur.execute("""
        SELECT o.first_event, COUNT(*),
               ROUND(AVG(o.result_r)::numeric, 4), ROUND(SUM(o.result_r)::numeric, 2)
        FROM bt.run r JOIN bt.setup s ON s.run_id = r.id JOIN bt.outcome o ON o.setup_id = s.id
        WHERE r.id = %s GROUP BY o.first_event ORDER BY 2 DESC
    """, (run_id,))
    print("\n=== BY EVENT ===")
    print(f"{'Event':<16} {'Cnt':>5} {'AvgR':>8} {'TotR':>10}")
    for r in cur.fetchall():
        print(f"{r[0]:<16} {r[1]:>5} {r[2] if r[2] else 0:>8} {r[3] if r[3] else 0:>10}")

    # By score
    cur.execute("""
        SELECT CASE
                 WHEN s.score < 30 THEN '<30'
                 WHEN s.score < 40 THEN '30-39'
                 WHEN s.score < 50 THEN '40-49'
                 WHEN s.score < 60 THEN '50-59'
                 ELSE '60+'
               END, COUNT(*),
               SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
               SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END),
               ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
               ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 2)
        FROM bt.run r JOIN bt.setup s ON s.run_id = r.id JOIN bt.outcome o ON o.setup_id = s.id
        WHERE r.id = %s GROUP BY 1 ORDER BY 1
    """, (run_id,))
    print("\n=== BY SCORE ===")
    print(f"{'Score':<10} {'Set':>5} {'Ent':>5} {'Win':>4} {'AvgR':>8} {'TotR':>10}")
    for r in cur.fetchall():
        print(f"{r[0]:<10} {r[1]:>5} {r[2]:>5} {r[3]:>4} {r[4] if r[4] else 0:>8} {r[5] if r[5] else 0:>10}")

    # Win rate for entries
    cur.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END),
               ROUND(AVG(o.result_r)::numeric, 4),
               ROUND(AVG(o.mfe_r)::numeric, 4),
               ROUND(AVG(o.mae_r)::numeric, 4)
        FROM bt.run r JOIN bt.setup s ON s.run_id = r.id JOIN bt.outcome o ON o.setup_id = s.id
        WHERE r.id = %s AND o.entry_touched = true
    """, (run_id,))
    r = cur.fetchone()
    if r and r[0]:
        wr = round(r[1] / r[0] * 100, 1)
        print(f"\n=== ENTRY STATS ===")
        print(f"Entries: {r[0]}, Wins: {r[1]}, Win rate: {wr}%, Avg R: {r[2]}, Avg MFE: {r[3]}, Avg MAE: {r[4]}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
