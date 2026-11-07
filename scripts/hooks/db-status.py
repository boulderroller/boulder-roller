"""
db-status.py — Platform status query for BoulderRoller staging.
Runs inside the API container via: docker compose exec -T api python3 /tmp/db_status.py
Uses direct HTTP to Supabase (avoids SDK version conflicts).
"""
import os, sys, json
sys.path.insert(0, "/app")
import httpx

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
headers = {"apikey": key}
if not key.startswith("sb_secret_"):
    headers["Authorization"] = "Bearer " + key


def count(table, extra=""):
    h = dict(headers)
    h["Prefer"] = "count=exact"
    h["Range"] = "0-0"
    r = httpx.get(url + "/rest/v1/" + table + "?select=id" + extra, headers=h)
    cr = r.headers.get("content-range", "")
    return cr.split("/")[-1] if "/" in cr else "?"


def query(table, select="*", extra=""):
    r = httpx.get(url + "/rest/v1/" + table + "?select=" + select + extra, headers=headers)
    return r.json()


# --- Core counts ---
pat_count = count("patterns_climb")
sig_count = count("patterns_climb", "&signature_hex=not.is.null")
vault_count = count("indexed_vaults")
lb_count = count("vault_leaderboards")

print("=== Platform Status ===")
print("Climb patterns:      " + str(pat_count))
print("  With signature:    " + str(sig_count))
try:
    print("  Without signature: " + str(int(pat_count) - int(sig_count)))
except:
    pass
print("Indexed vaults:      " + str(vault_count))
print("Leaderboard entries: " + str(lb_count))

# --- Top point holders ---
try:
    pts = query("wallet_points", "wallet,total_points", "&order=total_points.desc&limit=5")
    if isinstance(pts, list) and pts:
        print("")
        print("=== Top 5 Point Holders ===")
        for p in pts:
            w = str(p.get("wallet", "?"))[:12]
            tp = p.get("total_points", 0)
            print("  " + w + "...  " + "{:,.0f}".format(float(tp)) + " pts")
except Exception as e:
    print("Points: " + str(e))

# --- Vault stakes ---
try:
    sc = count("vault_stakes")
    print("")
    print("Vault stakes:        " + str(sc))
except:
    pass

# --- Recent rides ---
try:
    rc = count("activities")
    rides = query("activities", "id,user_id,created_at,tss", "&order=created_at.desc&limit=3")
    print("")
    print("=== Recent Rides (" + str(rc) + " total) ===")
    if isinstance(rides, list):
        for r in rides:
            if isinstance(r, dict):
                ca = str(r.get("created_at", "?"))[:16]
                w = str(r.get("user_id", "?"))[:12]
                tss = str(r.get("tss", "?"))
                print("  " + ca + "  user=" + w + "...  TSS=" + tss)
    elif isinstance(rides, dict) and "message" in rides:
        print("  (table may not exist: " + rides["message"] + ")")
except Exception as e:
    print("Rides: " + str(e))

# --- Supply state ---
try:
    supply = query("dung_supply_state", "*", "&limit=1")
    if isinstance(supply, list) and supply:
        s = supply[0]
        print("")
        print("=== Supply State ===")
        for k in ["max_supply", "total_minted", "total_burned", "circulating_supply"]:
            v = s.get(k, "?")
            label = k.replace("_", " ").title()
            if isinstance(v, (int, float)):
                print("  " + (label + ":").ljust(22) + "{:>15,.0f}".format(v))
            else:
                print("  " + (label + ":").ljust(22) + str(v))
except Exception as e:
    print("Supply: " + str(e))

# --- Economic ledger ---
try:
    ev_count = count("economic_events")
    print("")
    print("Economic events:     " + str(ev_count))
except:
    pass

print("")
print("=== Done ===")
