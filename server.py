"""
Servidor de leilão distribuído.

Uso:
    python server.py [porta]

Comandos do console admin:
    add                             cadastra um item (modo interativo:
                                    pede o nome e depois o lance inicial)
    close <item_id>                 encerra o leilão de um item
    list                            lista os itens e o estado atual
    clients                         lista compradores conectados
    help                            mostra a ajuda
    quit                            encerra o servidor

Protocolo: JSON por linha sobre TCP.
"""
import hashlib
import json
import os
import socket
import ssl
import sys
import threading
from datetime import datetime

# Habilita ANSI no Windows e força UTF-8 na saída.
if os.name == "nt":
    os.system("")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

HOST = "0.0.0.0"
DEFAULT_PORT = 5000
HISTORY_FILE = "auction_history.log"

# Credenciais de teste. Em produção viria de um banco seguro.
USERS = {
    "Shaolin_Matador_de_Porco": hashlib.sha256(b"senha123").hexdigest(),
    "Pedrin_do_Pneu": hashlib.sha256(b"senha456").hexdigest(),
    "JP_Tintas": hashlib.sha256(b"senha789").hexdigest(),
    "Breu_Autopeças": hashlib.sha256(b"senha654").hexdigest(),
    "admin": hashlib.sha256(b"admin").hexdigest(),
}

# ============================================================
#  UI helpers (cores ANSI + formatação)
# ============================================================
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"
    BR_RED = "\033[91m"
    BR_GREEN = "\033[92m"
    BR_YELLOW = "\033[93m"
    BR_CYAN = "\033[96m"
    BR_MAGENTA = "\033[95m"
    BR_WHITE = "\033[97m"


def money(v: float) -> str:
    """Formata valor como R$ 1.234,56 (padrão brasileiro)."""
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def parse_brl(s: str) -> float:
    """Aceita '3000', '3000.50', '3000,50', '3.000,50', 'R$ 3.000,50', 'R$: 3.000,50'."""
    s = s.strip().replace("R$", "").replace(":", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def banner() -> None:
    w = 62
    line = "═" * w
    print(f"\n{C.CYAN}╔{line}╗{C.RESET}")
    print(f"{C.CYAN}║{C.BOLD}{C.BR_WHITE}{'FABIO LEILÕES'.center(w)}{C.RESET}{C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}║{C.DIM}{'Sistemas Paralelos e Distribuídos'.center(w)}{C.RESET}{C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}╚{line}╝{C.RESET}\n")


def show_help() -> None:
    w = 66  # largura interna
    top = "╭" + "─" * w + "╮"
    bot = "╰" + "─" * w + "╯"
    sep = "├" + "─" * w + "┤"

    def inner(text: str) -> str:
        return f"{C.BR_CYAN}│{C.RESET}{pad(text, w)}{C.BR_CYAN}│{C.RESET}"

    title = " SERVIDOR DE LEILÃO — COMANDOS "
    title_line = pad(f"{C.BOLD}{C.BR_WHITE}{title}{C.RESET}", w, "c")

    sections = [
        ("LEILÃO", [
            ("add",          "cadastra um item (modo interativo)"),
            ("close <id>",   "encerra o leilão de um item"),
        ]),
        ("CONSULTA", [
            ("list",         "mostra a tabela de itens"),
            ("clients",      "lista compradores conectados"),
        ]),
        ("SISTEMA", [
            ("help",         "mostra esta ajuda"),
            ("quit",         "encerra o servidor"),
        ]),
    ]

    print(f"\n{C.BR_CYAN}{top}{C.RESET}")
    print(f"{C.BR_CYAN}│{C.RESET}{title_line}{C.BR_CYAN}│{C.RESET}")
    print(f"{C.BR_CYAN}{sep}{C.RESET}")
    for i, (name, cmds) in enumerate(sections):
        print(inner(f"  {C.BR_YELLOW}▸ {name}{C.RESET}"))
        for c, desc in cmds:
            cmd_col = f"{C.BOLD}{c}{C.RESET}"
            line = f"      {pad(cmd_col, 16)}{C.DIM}·{C.RESET}  {desc}"
            print(inner(line))
        if i < len(sections) - 1:
            print(inner(""))
    print(f"{C.BR_CYAN}{bot}{C.RESET}\n")


def log_info(msg: str) -> None:
    print(f"{C.GREY}[{now_hms()}]{C.RESET} {C.CYAN}ℹ{C.RESET}  {msg}")


def log_ok(msg: str) -> None:
    print(f"{C.GREY}[{now_hms()}]{C.RESET} {C.BR_GREEN}✓{C.RESET}  {msg}")


def log_warn(msg: str) -> None:
    print(f"{C.GREY}[{now_hms()}]{C.RESET} {C.BR_YELLOW}!{C.RESET}  {msg}")


def log_err(msg: str) -> None:
    print(f"{C.GREY}[{now_hms()}]{C.RESET} {C.BR_RED}✗{C.RESET}  {msg}")


def log_event(tag: str, color: str, msg: str) -> None:
    print(f"{C.GREY}[{now_hms()}]{C.RESET} {color}[{tag}]{C.RESET} {msg}")


def display_width(s: str) -> int:
    """Comprimento visível da string (ignora ANSI)."""
    import re
    return len(re.sub(r"\x1b\[[0-9;]*m", "", s))


def pad(s: str, width: int, align: str = "l") -> str:
    pad_len = width - display_width(s)
    if pad_len <= 0:
        return s
    if align == "r":
        return " " * pad_len + s
    if align == "c":
        left = pad_len // 2
        return " " * left + s + " " * (pad_len - left)
    return s + " " * pad_len


def render_items_table(items: list[dict]) -> str:
    """Tabela colorida de itens."""
    if not items:
        return f"{C.DIM}  (nenhum item cadastrado){C.RESET}"

    headers = ["ID", "Status", "Item", "Lance atual", "Autor"]
    rows = []
    for it in items:
        status_raw = "aberto" if it["open"] else "encerrado"
        if it["open"]:
            status = f"{C.BR_GREEN}● aberto{C.RESET}"
        else:
            status = f"{C.GREY}○ encerrado{C.RESET}"
        bidder = it["bidder"] or f"{C.DIM}—{C.RESET}"
        rows.append([
            f"{C.BOLD}#{it['item_id']}{C.RESET}",
            status,
            it["name"],
            f"{C.BOLD}{money(it['current_bid'])}{C.RESET}",
            bidder,
        ])

    widths = [max(display_width(headers[i]),
                  max(display_width(r[i]) for r in rows)) for i in range(len(headers))]

    top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    mid = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    bot = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

    def row_line(cells):
        parts = [" " + pad(c, widths[i]) + " " for i, c in enumerate(cells)]
        return "│" + "│".join(parts) + "│"

    out = [f"{C.CYAN}{top}{C.RESET}"]
    out.append(f"{C.CYAN}│{C.RESET}" + "│".join(
        f"{C.BOLD} " + pad(h, widths[i]) + f" {C.RESET}" for i, h in enumerate(headers)
    ) + f"{C.CYAN}│{C.RESET}")
    out.append(f"{C.CYAN}{mid}{C.RESET}")
    for r in rows:
        out.append(f"{C.CYAN}│{C.RESET}" + "│".join(
            " " + pad(c, widths[i]) + " " for i, c in enumerate(r)
        ) + f"{C.CYAN}│{C.RESET}")
    out.append(f"{C.CYAN}{bot}{C.RESET}")
    return "\n".join(out)


# ============================================================
#  Servidor
# ============================================================
class AuctionServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.items: dict[int, dict] = {}
        self.next_id = 1
        self.clients: dict[socket.socket, dict] = {}
        self.lock = threading.Lock()
        self.running = True
        self.sock: socket.socket | None = None

    # ---------- Ciclo de vida ---------- #
    def start(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(32)

        tls_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_ctx.load_cert_chain("cert.pem", "key.pem")

        banner()
        log_ok(f"Escutando em {C.BOLD}{self.host}:{self.port}{C.RESET} {C.BR_GREEN}[TLS]{C.RESET}")
        log_info(f"Usuários cadastrados: {C.BOLD}{len(USERS)}{C.RESET} "
                 f"{C.DIM}(digite 'help' para ver os comandos){C.RESET}")
        print()
        threading.Thread(target=self.admin_console, daemon=True).start()

        while self.running:
            try:
                raw_conn, addr = self.sock.accept()
                conn = tls_ctx.wrap_socket(raw_conn, server_side=True)
            except (OSError, ssl.SSLError):
                break
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(
                target=self.handle_client, args=(conn, addr), daemon=True
            ).start()

    def shutdown(self) -> None:
        if not self.running:
            return
        log_warn("Encerrando servidor...")
        self.running = False
        with self.lock:
            for iid, it in list(self.items.items()):
                if it["open"]:
                    it["open"] = False
                    it["closed_at"] = datetime.now().isoformat()
                    self._persist_item_locked(iid, it)
            for c in list(self.clients.keys()):
                try:
                    c.close()
                except OSError:
                    pass
            self.clients.clear()
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        log_ok("Servidor encerrado. Até mais!")

    # ---------- Rede ---------- #
    def send_json(self, conn: socket.socket, obj: dict) -> None:
        try:
            data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
            conn.sendall(data)
        except OSError:
            pass

    def broadcast(self, obj: dict, exclude: socket.socket | None = None) -> None:
        with self.lock:
            targets = [c for c in self.clients if c is not exclude]
        for c in targets:
            self.send_json(c, obj)

    def handle_client(self, conn: socket.socket, addr) -> None:
        log_info(f"Nova conexão de {C.BOLD}{addr[0]}:{addr[1]}{C.RESET}")
        buf = b""
        user: str | None = None
        try:
            while self.running:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    msg = self._parse_msg(line)
                    if msg is None:
                        self.send_json(
                            conn,
                            {"type": "error", "message": "json inválido"},
                        )
                        continue
                    if user is None:
                        user = self._try_auth(conn, addr, msg)
                        if user is None:
                            return
                    else:
                        self._dispatch(conn, user, msg)
        except (ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            with self.lock:
                self.clients.pop(conn, None)
            try:
                conn.close()
            except OSError:
                pass
            if user:
                log_warn(f"{C.BOLD}{user}{C.RESET} desconectou")

    @staticmethod
    def _parse_msg(raw: bytes) -> dict | None:
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ---------- Autenticação ---------- #
    def _try_auth(self, conn: socket.socket, addr, msg: dict) -> str | None:
        if msg.get("type") != "auth":
            self.send_json(
                conn, {"type": "error", "message": "autentique-se primeiro"}
            )
            return None
        u = msg.get("user", "")
        p = msg.get("password", "")
        expected = USERS.get(u)
        got = hashlib.sha256(p.encode("utf-8")).hexdigest()
        if not expected or expected != got:
            self.send_json(
                conn, {"type": "auth_fail", "message": "credenciais inválidas"}
            )
            log_err(f"Falha de autenticação de {addr[0]}:{addr[1]}")
            return None
        with self.lock:
            self.clients[conn] = {"user": u, "addr": addr}
        self.send_json(conn, {"type": "auth_ok", "user": u})
        self._send_state(conn)
        log_ok(f"{C.BR_GREEN}{C.BOLD}{u}{C.RESET} autenticado ({addr[0]}:{addr[1]})")
        return u

    # ---------- Mensagens ---------- #
    def _dispatch(self, conn: socket.socket, user: str, msg: dict) -> None:
        t = msg.get("type")
        if t == "bid":
            self._handle_bid(conn, user, msg)
        elif t == "list":
            self._send_state(conn)
        else:
            self.send_json(conn, {"type": "error", "message": f"tipo desconhecido: {t}"})

    def _handle_bid(self, conn: socket.socket, user: str, msg: dict) -> None:
        try:
            item_id = int(msg.get("item_id"))
            value = float(msg.get("value"))
        except (TypeError, ValueError):
            self.send_json(conn, {"type": "error", "message": "lance inválido"})
            return
        payload: dict | None = None
        with self.lock:
            it = self.items.get(item_id)
            if not it:
                self.send_json(conn, {"type": "error", "message": "item não encontrado"})
                return
            if not it["open"]:
                self.send_json(conn, {"type": "error", "message": "leilão encerrado"})
                return
            if value <= it["current_bid"]:
                self.send_json(
                    conn,
                    {
                        "type": "error",
                        "message": f"lance deve ser maior que o atual ({money(it['current_bid'])})",
                    },
                )
                return
            it["current_bid"] = value
            it["bidder"] = user
            it["history"].append(
                {"time": datetime.now().isoformat(), "bidder": user, "value": value}
            )
            payload = {
                "type": "new_bid",
                "item_id": item_id,
                "name": it["name"],
                "bidder": user,
                "value": value,
            }
            name = it["name"]
        if payload is not None:
            self.broadcast(payload)
            log_event(
                "LANCE", C.BR_YELLOW,
                f"{C.BOLD}{user}{C.RESET} → item #{item_id} '{name}' "
                f"por {C.BOLD}{money(value)}{C.RESET}",
            )

    def _send_state(self, conn: socket.socket) -> None:
        with self.lock:
            items = [
                {
                    "item_id": iid,
                    "name": it["name"],
                    "current_bid": it["current_bid"],
                    "bidder": it["bidder"],
                    "open": it["open"],
                }
                for iid, it in self.items.items()
            ]
        self.send_json(conn, {"type": "state", "items": items})

    # ---------- Console admin ---------- #
    def admin_console(self) -> None:
        show_help()
        while self.running:
            try:
                prompt = f"{C.BR_MAGENTA}{C.BOLD}admin{C.RESET}{C.BR_MAGENTA}❯{C.RESET} "
                line = input(prompt).strip()
            except EOFError:
                self.shutdown()
                return
            if not line:
                continue
            parts = line.split()
            cmd = parts[0].lower()
            if cmd in ("add", "novo"):
                try:
                    name = input(
                        f"  {C.BR_CYAN}▸{C.RESET} {C.BOLD}Nome do item para leilão:{C.RESET} "
                    ).strip()
                except EOFError:
                    self.shutdown()
                    return
                if not name:
                    log_err("nome não pode ficar vazio — cadastro cancelado")
                    continue
                try:
                    raw = input(
                        f"  {C.BR_CYAN}▸{C.RESET} {C.BOLD}Lance inicial: R$:{C.RESET} "
                    ).strip()
                except EOFError:
                    self.shutdown()
                    return
                try:
                    starting = parse_brl(raw)
                except ValueError:
                    log_err(f"valor inválido: '{raw}' — cadastro cancelado")
                    continue
                if starting < 0:
                    log_err("lance inicial não pode ser negativo — cadastro cancelado")
                    continue
                self._add_item(name, starting)
            elif cmd in ("close", "encerrar"):
                if len(parts) != 2:
                    log_err("uso: close <item_id>")
                    continue
                try:
                    iid = int(parts[1])
                except ValueError:
                    log_err("id inválido")
                    continue
                self._close_item(iid)
            elif cmd in ("list", "ls", "itens"):
                self._list_items()
            elif cmd in ("clients", "conectados"):
                self._list_clients()
            elif cmd in ("help", "ajuda", "?"):
                show_help()
            elif cmd in ("quit", "sair", "exit"):
                self.shutdown()
                return
            else:
                log_err(f"comando desconhecido: {cmd} {C.DIM}(digite 'help'){C.RESET}")

    def _add_item(self, name: str, starting: float) -> None:
        with self.lock:
            iid = self.next_id
            self.next_id += 1
            self.items[iid] = {
                "name": name,
                "starting": starting,
                "current_bid": starting,
                "bidder": None,
                "open": True,
                "history": [],
                "created_at": datetime.now().isoformat(),
            } 
        log_event(
            "ITEM", C.BR_CYAN,
            f"Item #{iid} '{C.BOLD}{name}{C.RESET}' cadastrado! "
            f"Lance inicial em: {C.BOLD}{money(starting)}{C.RESET}",
        )
        self.broadcast(
            {
                "type": "item_added",
                "item_id": iid,
                "name": name,
                "starting": starting,
            }
        )

    def _close_item(self, iid: int) -> None:
        with self.lock:
            it = self.items.get(iid)
            if not it:
                log_err("item não encontrado")
                return
            if not it["open"]:
                log_warn("leilão já encerrado")
                return
            it["open"] = False
            it["closed_at"] = datetime.now().isoformat()
            winner = it["bidder"]
            value = it["current_bid"]
            name = it["name"]
            self._persist_item_locked(iid, it)
        self.broadcast(
            {
                "type": "item_closed",
                "item_id": iid,
                "name": name,
                "winner": winner,
                "value": value,
            }
        )
        if winner:
            log_event(
                "ENCERRADO", C.BR_MAGENTA,
                f"item #{iid} '{name}' → vencedor {C.BOLD}{winner}{C.RESET} "
                f"por {C.BOLD}{money(value)}{C.RESET}",
            )
        else:
            log_event("ENCERRADO", C.GREY, f"item #{iid} '{name}' sem lances")

    def _list_items(self) -> None:
        with self.lock:
            items = [
                {
                    "item_id": iid,
                    "name": it["name"],
                    "current_bid": it["current_bid"],
                    "bidder": it["bidder"],
                    "open": it["open"],
                }
                for iid, it in self.items.items()
            ]
        total = len(items)
        abertos = sum(1 for it in items if it["open"])
        print()
        print(f"{C.BOLD}Itens do leilão{C.RESET} "
              f"{C.DIM}({total} total, {abertos} em aberto){C.RESET}")
        print(render_items_table(items))
        print()

    def _list_clients(self) -> None:
        with self.lock:
            entries = [(info["user"], info["addr"]) for info in self.clients.values()]
        print()
        if not entries:
            print(f"{C.DIM}  (nenhum comprador conectado){C.RESET}\n")
            return
        print(f"{C.BOLD}Compradores conectados ({len(entries)}){C.RESET}")
        for user, addr in entries:
            print(f"  {C.BR_GREEN}●{C.RESET} {C.BOLD}{user}{C.RESET} "
                  f"{C.DIM}({addr[0]}:{addr[1]}){C.RESET}")
        print()

    # ---------- Persistência ---------- #
    def _persist_item_locked(self, iid: int, item: dict) -> None:
        record = {
            "item_id": iid,
            "name": item["name"],
            "starting": item["starting"],
            "final_value": item["current_bid"],
            "winner": item["bidder"],
            "created_at": item.get("created_at"),
            "closed_at": item.get("closed_at"),
            "history": item["history"],
        }
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            log_err(f"erro ao gravar histórico: {e}")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = AuctionServer(HOST, port)
    try:
        server.start()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
