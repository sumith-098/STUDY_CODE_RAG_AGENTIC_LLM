"""
rate_limiter.py  --  Free tier ko kabhi cross na hone dene wala "traffic police".

Do cheezein:
  1. QuotaManager     : Gemini ke RPM / TPM / RPD ko khud track karta hai.
                        Har Gemini call se PEHLE acquire() chalta hai.
                        - minute limit bhari  -> thoda wait karta hai (user ko pata bhi nahi chalta)
                        - din ki limit bhari  -> saaf message ke saath QuotaExceeded
                        RPD SQLite me save hota hai, isliye server restart par reset nahi hota.
  2. IPLimiter        : Ek hi user/IP spam kare to roke, taaki baaki users ka quota bacha rahe.
"""
import math
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .config import DATA_DIR, SQLITE_PATH, AVG_LLM_CALLS_PER_TURN, Limits
from .errors import QuotaExceeded

try:
    from zoneinfo import ZoneInfo
    # Google ka daily quota Pacific time ke midnight par reset hota hai.
    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # tzdata install na ho to approx fallback (UTC-8)
    _PACIFIC = timezone(timedelta(hours=-8))

def _now_pacific() -> datetime:
    """No input. Returns: abhi ka datetime Pacific timezone me."""
    return datetime.now(_PACIFIC)

def seconds_until_reset() -> int:
    """No input. Returns: Pacific midnight (daily quota reset) me kitne seconds bache (int)."""
    now = _now_pacific()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds())

def estimate_tokens(text: str) -> int:
    """Input: text. Returns: andaza (int) -- approx 4 characters = 1 token."""
    return len(text) // 4 + 1


class QuotaManager:
    def __init__(self, limits: dict[str, Limits], db_path=SQLITE_PATH):
        """
        Inputs:
          limits  : {'chat': Limits(rpm,tpm,rpd), 'embed': Limits(...)}  (safe limits)
          db_path : SQLite file jaha daily count save hota hai.
        """
        self.limits = limits
        self.db_path = db_path
        self._lock = threading.Lock()                 # threads ek saath counter na bigaade
        self._window = defaultdict(deque)             # bucket -> deque[(time, tokens)] pichhle 60s
        self._init_db()

    # ---------- SQLite helpers (RPD ke liye) ----------
    def _connect(self):
        """Returns: sqlite3.Connection. check_same_thread=False => alag threads se use ho sake."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        """Table banata hai: daily_usage(bucket, day, requests)."""
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS daily_usage (
                bucket TEXT NOT NULL, day TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (bucket, day))""")

    def _today(self) -> str:
        """Returns: Pacific date string 'YYYY-MM-DD'."""
        return _now_pacific().strftime("%Y-%m-%d")

    def _daily_count(self, bucket: str) -> int:
        """Input: bucket naam. Returns: aaj ke kitne requests ho chuke (int)."""
        with self._connect() as con:
            # execute(sql, params) -> cursor; fetchone() -> tuple ya None
            row = con.execute("SELECT requests FROM daily_usage WHERE bucket=? AND day=?",
                              (bucket, self._today())).fetchone()
        return row[0] if row else 0

    def _daily_increment(self, bucket: str):
        """Input: bucket. Aaj ka count +1 karta hai (upsert). Returns None."""
        with self._connect() as con:
            con.execute("""INSERT INTO daily_usage(bucket, day, requests) VALUES (?, ?, 1)
                           ON CONFLICT(bucket, day) DO UPDATE SET requests = requests + 1""",
                        (bucket, self._today()))

    # ---------- minute window ----------
    def _prune(self, bucket: str, now: float):
        """60 second se purani entries hata deta hai."""
        dq = self._window[bucket]
        while dq and now - dq[0][0] >= 60:
            dq.popleft()

    def _wait_needed(self, bucket: str, now: float, tokens: int) -> float:
        """
        Inputs: bucket, current time, is call ke estimated tokens.
        Returns: kitne seconds ruk-na padega (0 = abhi call kar sakte ho).
        """
        lim, dq = self.limits[bucket], self._window[bucket]
        wait = 0.0
        if len(dq) >= lim.rpm:                        # requests/minute bhar gaye
            wait = max(wait, dq[0][0] + 60 - now)
        used = sum(t for _, t in dq)
        if used + tokens > lim.tpm:                   # tokens/minute bhar gaye
            freed = 0
            for ts, tk in dq:                         # sabse purani entries kab expire hongi
                freed += tk
                if used - freed + tokens <= lim.tpm:
                    wait = max(wait, ts + 60 - now)
                    break
        return max(0.0, wait)

    # ---------- main API ----------
    def acquire(self, bucket: str, tokens: int = 0, max_wait: float = 25) -> None:
        """
        Gemini call se pehle chalao.
        Inputs:
          bucket   : 'chat' ya 'embed'
          tokens   : is call ke estimated tokens (estimate_tokens() se)
          max_wait : minute-limit par max kitne seconds ruk sakte ho
        Returns None jab call allowed ho. Raises QuotaExceeded (friendly message) warna.
        """
        lim = self.limits[bucket]
        if tokens > lim.tpm:
            raise QuotaExceeded("This input is too large for the free tier. Please shorten it and try again.")
        deadline = time.monotonic() + max_wait
        while True:
            with self._lock:
                if self._daily_count(bucket) >= lim.rpd:
                    secs = seconds_until_reset()
                    hrs = max(1, math.ceil(secs / 3600))
                    raise QuotaExceeded(
                        f"Today's free AI limit has been used up. It resets in about {hrs} hour(s); "
                        f"please try again then.", retry_after=secs)
                now = time.monotonic()
                self._prune(bucket, now)
                wait = self._wait_needed(bucket, now, tokens)
                if wait <= 0:                          # green signal: record karke jao
                    self._window[bucket].append((now, tokens))
                    self._daily_increment(bucket)
                    return
            if time.monotonic() + wait > deadline:
                raise QuotaExceeded(
                    f"There are a lot of requests right now. Please try again in "
                    f"{math.ceil(wait)} seconds.", retry_after=math.ceil(wait))
            time.sleep(min(wait, 2.0) + 0.05)         # thoda ruko, phir dobara check

    def status(self) -> dict:
        """
        No input. Returns (UI ke quota badge ke liye):
        {
          'chat':  {'used_today', 'limit_today', 'remaining_today', 'used_last_minute', 'limit_per_minute'},
          'embed': {... same ...},
          'approx_questions_left': int,   # chat remaining / AVG_LLM_CALLS_PER_TURN
          'resets_in_seconds': int
        }
        """
        out = {}
        with self._lock:
            now = time.monotonic()
            for bucket, lim in self.limits.items():
                self._prune(bucket, now)
                used = self._daily_count(bucket)
                out[bucket] = {
                    "used_today": used, "limit_today": lim.rpd,
                    "remaining_today": max(0, lim.rpd - used),
                    "used_last_minute": len(self._window[bucket]),
                    "limit_per_minute": lim.rpm,
                }
        out["approx_questions_left"] = int(out["chat"]["remaining_today"] / AVG_LLM_CALLS_PER_TURN)
        out["resets_in_seconds"] = seconds_until_reset()
        return out

    def daily_remaining_fraction(self, bucket: str = "chat") -> float:
        """Returns: 0.0-1.0, aaj ka kitna % quota bacha (verifier skip karne ke liye)."""
        with self._lock:
            lim = self.limits[bucket]
            return max(0, lim.rpd - self._daily_count(bucket)) / lim.rpd


class IPLimiter:
    """Simple sliding-window limiter: ek key (IP) ko window me max N events."""

    def __init__(self, max_events: int, window_seconds: int):
        """Inputs: max_events (int), window_seconds (int)."""
        self.max_events, self.window = max_events, window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Input: key (jaise IP). Returns None; limit cross hui to QuotaExceeded raise."""
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] >= self.window:
                dq.popleft()
            if len(dq) >= self.max_events:
                retry = math.ceil(self.window - (now - dq[0]))
                raise QuotaExceeded(f"Slow down a little! Please try again in {retry} seconds.",
                                    retry_after=retry)
            dq.append(now)