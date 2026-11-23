"""Banco de dados simples (SQLite): tudo fica numa tabela só, separado por 'kind'."""
import sqlite3, threading, time


class Store:
    def __init__(self, path):
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.l = threading.Lock()
        self.q("""CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, text TEXT,
            ts REAL, done INTEGER DEFAULT 0, due REAL, extra TEXT DEFAULT '')""")

    def q(self, sql, a=()):
        with self.l:
            cur = self.c.execute(sql, a)
            self.c.commit()
            return [dict(r) for r in cur.fetchall()], cur.lastrowid

    def add(self, kind, text, due=None, extra=""):
        return self.q("INSERT INTO items(kind,text,ts,due,extra) VALUES(?,?,?,?,?)",
                      (kind, text, time.time(), due, extra))[1]

    def list(self, kind, limit=200, asc=False):
        o = "ASC" if asc else "DESC"
        return self.q(f"SELECT * FROM items WHERE kind=? ORDER BY id {o} LIMIT ?", (kind, limit))[0]

    def get(self, id):
        r = self.q("SELECT * FROM items WHERE id=?", (id,))[0]
        return r[0] if r else None

    def update(self, id, **kw):
        if kw:
            cols = ",".join(k + "=?" for k in kw)
            self.q(f"UPDATE items SET {cols} WHERE id=?", (*kw.values(), id))

    def delete(self, id):
        self.q("DELETE FROM items WHERE id=?", (id,))

    def count(self, kind, open_only=False):
        sql = "SELECT COUNT(*) n FROM items WHERE kind=?" + (" AND done=0" if open_only else "")
        return self.q(sql, (kind,))[0][0]["n"]

    def due(self, now):
        return self.q("SELECT * FROM items WHERE kind='reminder' AND done=0 AND due<=?", (now,))[0]

    def clear(self, kind):
        self.q("DELETE FROM items WHERE kind=?", (kind,))

    def prune(self, kind, keep):
        self.q("DELETE FROM items WHERE kind=? AND id NOT IN "
               "(SELECT id FROM items WHERE kind=? ORDER BY id DESC LIMIT ?)", (kind, kind, keep))
