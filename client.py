"""
Cliente do leilão distribuído.

Uso:
    python client.py [host] [porta]

Comandos no prompt:
    bid <item_id> <valor>    envia um lance
    list                     mostra o estado atual dos itens
    help                     mostra a ajuda
    quit                     encerra o cliente
"""
import getpass
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import sys
import threading

# Habilita ANSI no Windows e força UTF-8 na saída.
if os.name == "nt":
    os.system("")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
SHARED_HMAC_KEY = b"leilao-shared-hmac-key-2026"


# ============================================================
#  UI helpers
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
    BR_BLUE = "\033[94m"
    BR_MAGENTA = "\033[95m"
    BR_CYAN = "\033[96m"
    BR_WHITE = "\033[97m"


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def display_width(s: str) -> int:
    return len(ANSI_RE.sub("", s))


def pad(s: str, width: int, align: str = "l") -> str:
    diff = width - display_width(s)
    if diff <= 0:
        return s
    if align == "r":
        return " " * diff + s
    if align == "c":
        left = diff // 2
        return " " * left + s + " " * (diff - left)
    return s + " " * diff


def money(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def money_plain(v: float) -> str:
    """Valor no padrão brasileiro sem 'R$' na frente (ex: 3.000,00)."""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def prompt_str(user: str) -> str:
    return f"{C.BR_GREEN}{user}{C.RESET}{C.BR_CYAN}❯{C.RESET} "


def banner(host: str, port: int) -> None:
    w = 62
    line = "═" * w
    print(f"\n{C.CYAN}╔{line}╗{C.RESET}")
    print(f"{C.CYAN}║{C.BOLD}{C.BR_WHITE}{'LEILÃO DISTRIBUÍDO — CLIENTE'.center(w)}{C.RESET}{C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}║{C.DIM}{f'conectando a {host}:{port}'.center(w)}{C.RESET}{C.CYAN}║{C.RESET}")
    print(f"{C.CYAN}╚{line}╝{C.RESET}\n")


def show_help() -> str:
    return (
        f"\n{C.BR_CYAN}{C.BOLD}┌─ Comandos ────────────────────────────────────────┐{C.RESET}\n"
        f"{C.BR_CYAN}│{C.RESET} {C.BOLD}bid{C.RESET} <item_id> <valor>   envia um lance          {C.BR_CYAN}│{C.RESET}\n"
        f"{C.BR_CYAN}│{C.RESET} {C.BOLD}list{C.RESET}                     mostra o estado atual  {C.BR_CYAN}│{C.RESET}\n"
        f"{C.BR_CYAN}│{C.RESET} {C.BOLD}help{C.RESET}                     mostra esta ajuda       {C.BR_CYAN}│{C.RESET}\n"
        f"{C.BR_CYAN}│{C.RESET} {C.BOLD}quit{C.RESET}                     encerra o cliente       {C.BR_CYAN}│{C.RESET}\n"
        f"{C.BR_CYAN}└───────────────────────────────────────────────────┘{C.RESET}\n"
    )


def render_items_table(items: list[dict], own_user: str) -> str:
    if not items:
        return f"{C.DIM}  (nenhum item cadastrado ainda){C.RESET}"

    headers = ["ID", "Status", "Item", "Lance atual", "Autor"]
    rows = []
    for it in items:
        if it["open"]:
            status = f"{C.BR_GREEN}● aberto{C.RESET}"
        else:
            status = f"{C.GREY}○ encerrado{C.RESET}"
        bidder_raw = it["bidder"]
        if bidder_raw == own_user:
            bidder = f"{C.BR_GREEN}{C.BOLD}{bidder_raw} (você){C.RESET}"
        elif bidder_raw:
            bidder = bidder_raw
        else:
            bidder = f"{C.DIM}—{C.RESET}"
        value_color = C.BR_GREEN if bidder_raw == own_user else C.BOLD
        rows.append([
            f"{C.BOLD}#{it['item_id']}{C.RESET}",
            status,
            it["name"],
            f"{value_color}{money(it['current_bid'])}{C.RESET}",
            bidder,
        ])

    widths = [max(display_width(headers[i]),
                  max(display_width(r[i]) for r in rows)) for i in range(len(headers))]

    top = "┌" + "┬".join("─" * (w + 2) for w in widths) + "┐"
    mid = "├" + "┼".join("─" * (w + 2) for w in widths) + "┤"
    bot = "└" + "┴".join("─" * (w + 2) for w in widths) + "┘"

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


def sign(payload: bytes) -> str:
    return hmac.new(SHARED_HMAC_KEY, payload, hashlib.sha256).hexdigest()


def verify(payload: bytes, tag: str) -> bool:
    return hmac.compare_digest(sign(payload), tag or "")


# ============================================================
#  Cliente
# ============================================================
class AuctionClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.user: str | None = None
        self.running = True
        self.buf = b""
        self.print_lock = threading.Lock()

    # ---------- Rede ---------- #
    def connect(self) -> None:
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.connect((self.host, self.port))
        raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        tls_ctx = ssl.create_default_context()
        tls_ctx.check_hostname = False   # cert auto-assinado não tem hostname válido
        tls_ctx.verify_mode = ssl.CERT_NONE
        self.sock = tls_ctx.wrap_socket(raw_sock)

    def send_json(self, obj: dict) -> None:
        if not self.sock:
            return
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        envelope = {"sig": sign(body), "body": body.decode("utf-8")}
        try:
            self.sock.sendall((json.dumps(envelope) + "\n").encode("utf-8"))
        except OSError:
            self.running = False

    def recv_message(self) -> dict | None:
        assert self.sock is not None
        while b"\n" not in self.buf:
            try:
                chunk = self.sock.recv(4096)
            except OSError:
                return None
            if not chunk:
                return None
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        try:
            env = json.loads(line.decode("utf-8"))
            body = env["body"].encode("utf-8")
            if not verify(body, env.get("sig", "")):
                return None
            return json.loads(body)
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            return None

    # ---------- Autenticação ---------- #
    def authenticate(self, user: str, password: str) -> bool:
        self.send_json({"type": "auth", "user": user, "password": password})
        msg = self.recv_message()
        if not msg:
            print(f"{C.BR_RED}✗ conexão encerrada antes da autenticação{C.RESET}")
            return False
        if msg.get("type") == "auth_ok":
            self.user = user
            print(f"\n{C.BR_GREEN}✓ autenticado como {C.BOLD}{user}{C.RESET}\n")
            return True
        print(f"\n{C.BR_RED}✗ falha: {msg.get('message', 'credenciais inválidas')}{C.RESET}\n")
        return False

    # ---------- Listener ---------- #
    def listen_loop(self) -> None:
        while self.running:
            msg = self.recv_message()
            if msg is None:
                break
            self._render(msg)
        self.running = False
        self._write(
            f"\n{C.BR_RED}━━━ conexão encerrada pelo servidor ━━━{C.RESET}\n"
            f"{C.DIM}digite 'quit' para sair{C.RESET}\n"
            + prompt_str(self.user or "")
        )

    def _write(self, text: str) -> None:
        with self.print_lock:
            sys.stdout.write(text)
            sys.stdout.flush()

    def _reprompt(self) -> str:
        return prompt_str(self.user or "")

    def _render(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "new_bid":
            self._render_new_bid(msg)
        elif t == "item_added":
            self._render_item_added(msg)
        elif t == "item_closed":
            self._render_item_closed(msg)
        elif t == "state":
            self._render_state(msg)
        elif t == "error":
            self._write(
                f"\n{C.BR_RED}✗ erro: {msg.get('message', '')}{C.RESET}\n"
                + self._reprompt()
            )

    def _render_new_bid(self, msg: dict) -> None:
        bidder = msg["bidder"]
        value = msg["value"]
        name = msg["name"]
        iid = msg["item_id"]
        is_mine = bidder == self.user

        if is_mine:
            color = C.BR_GREEN
            tag = "SEU LANCE REGISTRADO"
            extra = f"{C.DIM}você está vencendo agora!{C.RESET}"
        else:
            color = C.BR_YELLOW
            tag = "NOVO LANCE"
            extra = f"{C.BR_RED}⚠ cubra para voltar a liderar!{C.RESET}"

        bar = "━" * 60
        self._write(
            f"\n{color}{bar}{C.RESET}\n"
            f" {color}{C.BOLD}▶ [{tag}]{C.RESET}  item {C.BOLD}#{iid}{C.RESET} "
            f"'{C.BOLD}{name}{C.RESET}'\n"
            f"   {C.BOLD}{money(value)}{C.RESET} por {C.CYAN}{C.BOLD}{bidder}{C.RESET}  "
            f"{extra}\n"
            f"{color}{bar}{C.RESET}\n"
            + self._reprompt()
        )

    def _render_item_added(self, msg: dict) -> None:
        iid = msg["item_id"]
        name = msg["name"]
        valor = money_plain(msg["starting"])
        bar = "━" * 72
        line = (
            f"{C.BOLD}ID:{C.RESET} {C.BR_WHITE}{iid}{C.RESET} "
            f"{C.DIM}|{C.RESET} "
            f"{C.BOLD}Item:{C.RESET} {C.BR_WHITE}{name}{C.RESET} "
            f"{C.DIM}|{C.RESET} "
            f"{C.BOLD}Lance:{C.RESET} {C.BR_GREEN}R$: {valor}{C.RESET}"
        )
        self._write(
            f"\n{C.BR_CYAN}{bar}{C.RESET}\n"
            f" {C.BR_CYAN}{C.BOLD}● [NOVO ITEM DISPONÍVEL]{C.RESET}\n"
            f" {line}\n"
            f" {C.DIM}digite 'bid {iid} <valor>' para dar um lance{C.RESET}\n"
            f"{C.BR_CYAN}{bar}{C.RESET}\n"
            + self._reprompt()
        )

    def _render_item_closed(self, msg: dict) -> None:
        winner = msg.get("winner")
        value = msg.get("value", 0.0)
        iid = msg["item_id"]
        name = msg["name"]
        bar = "═" * 60

        if winner is None:
            color = C.GREY
            result = f"{C.DIM}encerrado sem lances{C.RESET}"
        elif winner == self.user:
            color = C.BR_BLUE
            result = (
                f"{C.BR_BLUE}{C.BOLD}★ VOCÊ VENCEU! ★{C.RESET}  "
                f"por {C.BOLD}{money(value)}{C.RESET}"
            )
        else:
            color = C.BR_MAGENTA
            result = (
                f"vencedor: {C.BOLD}{winner}{C.RESET} por "
                f"{C.BOLD}{money(value)}{C.RESET}"
            )

        self._write(
            f"\n{color}{bar}{C.RESET}\n"
            f" {color}{C.BOLD}■ [LEILÃO ENCERRADO]{C.RESET}  item #{iid} '{C.BOLD}{name}{C.RESET}'\n"
            f"   {result}\n"
            f"{color}{bar}{C.RESET}\n"
            + self._reprompt()
        )

    def _render_state(self, msg: dict) -> None:
        items = msg.get("items", [])
        total = len(items)
        abertos = sum(1 for it in items if it["open"])
        header = (
            f"\n{C.BOLD}Estado do leilão{C.RESET} "
            f"{C.DIM}({total} itens, {abertos} em aberto){C.RESET}\n"
        )
        self._write(
            header
            + render_items_table(items, self.user or "")
            + "\n"
            + self._reprompt()
        )

    # ---------- REPL ---------- #
    def repl(self) -> None:
        self._write(show_help() + self._reprompt())
        while self.running:
            try:
                line = input().strip()
            except EOFError:
                break
            if not line:
                self._write(self._reprompt())
                continue
            parts = line.split()
            cmd = parts[0].lower()
            if cmd in ("bid", "lance"):
                if len(parts) != 3:
                    self._write(
                        f"{C.BR_YELLOW}uso: bid <item_id> <valor>{C.RESET}\n"
                        + self._reprompt()
                    )
                    continue
                try:
                    iid = int(parts[1])
                    val = float(parts[2].replace(",", "."))
                except ValueError:
                    self._write(
                        f"{C.BR_RED}✗ valores inválidos{C.RESET}\n" + self._reprompt()
                    )
                    continue
                if val <= 0:
                    self._write(
                        f"{C.BR_RED}✗ valor deve ser positivo{C.RESET}\n"
                        + self._reprompt()
                    )
                    continue
                self.send_json({"type": "bid", "item_id": iid, "value": val})
            elif cmd in ("list", "ls", "itens"):
                self.send_json({"type": "list"})
            elif cmd in ("help", "ajuda", "?"):
                self._write(show_help() + self._reprompt())
            elif cmd in ("quit", "sair", "exit"):
                self.running = False
                break
            else:
                self._write(
                    f"{C.BR_RED}✗ comando desconhecido:{C.RESET} {cmd} "
                    f"{C.DIM}(digite 'help'){C.RESET}\n"
                    + self._reprompt()
                )

    def close(self) -> None:
        self.running = False
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT

    banner(host, port)

    try:
        user = input(f"{C.BOLD}usuário:{C.RESET} ").strip()
        password = getpass.getpass(f"{C.BOLD}senha:{C.RESET} ")
    except (EOFError, KeyboardInterrupt):
        print()
        return

    client = AuctionClient(host, port)
    try:
        client.connect()
    except OSError as e:
        print(f"\n{C.BR_RED}✗ não foi possível conectar: {e}{C.RESET}")
        return

    if not client.authenticate(user, password):
        client.close()
        return

    threading.Thread(target=client.listen_loop, daemon=True).start()
    try:
        client.repl()
    except KeyboardInterrupt:
        pass
    client.close()
    print(f"\n{C.BR_CYAN}até logo, {C.BOLD}{user}{C.RESET}{C.BR_CYAN}!{C.RESET}\n")


if __name__ == "__main__":
    main()
