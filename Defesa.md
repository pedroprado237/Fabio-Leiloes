# Defesa — G1 · Sistemas Paralelos e Distribuídos

**Arquivos:** `server.py` e `client.py` · **Linguagem:** Python 3.10+

---

## O que foi feito (resumo em 3 linhas)

Um servidor central aceita múltiplos compradores ao mesmo tempo. Cada comprador conectado recebe notificações em tempo real de novos lances e do encerramento do leilão. A comunicação usa **TCP** e cada conexão roda em uma **thread separada**.

---

## 1. Sockets TCP

**Por que TCP e não UDP?**
TCP garante entrega e ordem. Em um leilão, um lance que se perde ou chega fora de ordem é inaceitável — UDP não teria essa garantia.

**Servidor abre o socket e aguarda conexões:**
```python
# server.py — dentro de start()
self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # evita "porta em uso" ao reiniciar
self.sock.bind(("0.0.0.0", self.port))  # aceita de qualquer IP da rede
self.sock.listen(32)

conn, addr = self.sock.accept()  # bloqueia até alguém conectar
```

**Cliente se conecta:**
```python
# client.py — dentro de connect()
self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
self.sock.connect((self.host, self.port))
```

---

## 2. Threads para conexões concorrentes

**Problema:** se o servidor atendesse um cliente de cada vez, enquanto processasse o lance do comprador A, o comprador B ficaria travado esperando.

**Solução:** cada cliente aceito ganha sua própria thread.

```python
# server.py — dentro do loop de accept()
threading.Thread(
    target=self.handle_client,
    args=(conn, addr),
    daemon=True   # morre automaticamente quando o servidor fecha
).start()
```

**Threads do servidor:**

| Thread | O que faz |
|--------|-----------|
| Principal (`start`) | Loop de `accept()` — aguarda novas conexões |
| `admin_console` | Lê comandos do admin (`add`, `close`, `list`...) |
| Uma `handle_client` por cliente | Processa mensagens daquele cliente |

**Threads do cliente:**

| Thread | O que faz |
|--------|-----------|
| Principal (`repl`) | Lê `input()` do usuário e envia comandos |
| `listen_loop` | Fica em `recv()` e imprime notificações que chegam |

Isso permite receber um aviso de novo lance **enquanto o usuário está digitando**, sem travar.

---

## 3. Gerenciar estado do leilão

O estado fica num dicionário dentro do servidor, protegido por um **Lock**:

```python
self.items: dict[int, dict] = {}   # item_id → dados do item
self.clients: dict[socket, dict]   # conexão → {user, addr}
self.lock = threading.Lock()
```

Cada item guardado tem:
```python
{
    "name": "iPhone 15",
    "current_bid": 1000.0,   # lance atual (vai subindo)
    "bidder": None,          # quem está vencendo
    "open": True,            # False quando encerrar
    "history": [],           # todos os lances com timestamp
}
```

---

## 4. Cadastrar item (comando `add`)

```python
# server.py — _add_item()
with self.lock:                  # bloqueia outras threads enquanto mexe no estado
    iid = self.next_id
    self.next_id += 1
    self.items[iid] = { "name": name, "current_bid": starting, "open": True, ... }

self.broadcast({"type": "item_added", "item_id": iid, "name": name, "starting": starting})
```

O `broadcast` notifica **todos os clientes conectados** que um novo item está disponível.

---

## 5. Receber e armazenar lances (identificando o autor)

```python
# server.py — _handle_bid()
with self.lock:
    it = self.items.get(item_id)

    # validação
    if not it["open"]:
        return error("leilão encerrado")
    if value <= it["current_bid"]:
        return error(f"lance deve ser maior que o atual ({it['current_bid']})")

    # atualiza estado
    it["current_bid"] = value
    it["bidder"] = user          # ← identifica o autor
    it["history"].append({"time": ..., "bidder": user, "value": value})
    payload = {"type": "new_bid", "bidder": user, "value": value, ...}

self.broadcast(payload)          # notifica todos fora do lock
```

**Decisão importante:** validação + atualização estão **dentro do mesmo `with self.lock`**. Se estivessem separados, dois lances chegando ao mesmo tempo poderiam ambos passar na validação antes de qualquer um atualizar — gerando um estado errado.

---

## 6. Notificar compradores sobre o lance atual

O `broadcast` envia para todos os clientes conectados:

```python
# server.py — broadcast()
def broadcast(self, obj: dict, exclude=None) -> None:
    with self.lock:
        targets = [c for c in self.clients if c is not exclude]
    for c in targets:           # envia FORA do lock
        self.send_json(c, obj)
```

**Por que copiar a lista dentro do lock e enviar fora?**
O envio de rede pode ser lento. Se enviasse dentro do lock, um cliente com rede lenta travaria o servidor inteiro enquanto o lock estivesse ocupado. Copiando a lista e saindo do lock, apenas a leitura do estado é protegida.

No cliente, a `listen_loop` recebe e exibe imediatamente:
```python
# client.py — _render_new_bid()
# exibe algo como:
# ▶ [NOVO LANCE]  item #1 'iPhone 15'
#    R$ 1.500,00 por JP_Tintas
```

---

## 7. Encerrar leilão e notificar vencedor

```python
# server.py — _close_item()
with self.lock:
    it["open"] = False
    it["closed_at"] = datetime.now().isoformat()
    winner = it["bidder"]
    value  = it["current_bid"]
    self._persist_item_locked(iid, it)   # grava no arquivo aqui dentro do lock

self.broadcast({
    "type": "item_closed",
    "winner": winner,    # ← vencedor
    "value": value,      # ← valor pago
    ...
})
```

Todos os clientes recebem e exibem:
```
■ [LEILÃO ENCERRADO]  item #1 'iPhone 15'
   vencedor: JP_Tintas por R$ 1.500,00
```
Se for o próprio vencedor: `★ VOCÊ VENCEU! ★`

---

## 8. Validar lances

```python
# server.py — _handle_bid(), dentro do with self.lock
if value <= it["current_bid"]:
    self.send_json(conn, {"type": "error", "message": "lance deve ser maior que o atual"})
    return
```

Simples e direto. A verificação ocorre **dentro do lock** — garantia de atomicidade (ver item 5).

---

## 9. Painel em tempo real no cliente

Duas threads no cliente trabalham ao mesmo tempo:
- Thread do REPL: lê o que o usuário digita.
- Thread `listen_loop`: fica bloqueada em `recv()` e imprime quando chega algo.

```python
# client.py — listen_loop()
while self.running:
    msg = self.recv_message()   # bloqueia aqui até chegar algo
    if msg is None:
        break
    self._render(msg)           # imprime na tela formatado
```

O `print_lock` evita que as duas threads escrevam no terminal ao mesmo tempo e embaralhem a saída:
```python
def _write(self, text: str) -> None:
    with self.print_lock:
        sys.stdout.write(text)
        sys.stdout.flush()
```

---

## 10. Persistência em arquivo

```python
# server.py — _persist_item_locked()
record = {
    "item_id": iid,
    "name": ...,
    "final_value": item["current_bid"],
    "winner": item["bidder"],
    "created_at": ..., "closed_at": ...,
    "history": item["history"],   # ← todos os lances intermediários
}
with open("auction_history.log", "a", encoding="utf-8") as f:
    f.write(json.dumps(record) + "\n")
```

Formato **JSON-lines**: cada linha é um item encerrado. Fácil de abrir com qualquer ferramenta. Gravado no `close` do item e no `quit` do servidor (para itens ainda abertos).

---

## BÔNUS — Autenticação

Senhas guardadas como **hash SHA-256** (nunca em texto puro):
```python
USERS = {
    "Pedrin_do_Pneu": hashlib.sha256(b"senha456").hexdigest(),
}
```

No login, compara hashes com tempo constante (evita timing attack):
```python
got = hashlib.sha256(p.encode()).hexdigest()
if not hmac.compare_digest(expected, got):
    # nega acesso e fecha conexão
```

Antes de autenticar, qualquer mensagem que não seja `auth` é recusada.

---

## BÔNUS — Confidencialidade (TLS)

O TLS foi adicionado sobre o socket TCP existente. Todo o restante do código (protocolo JSON, HMAC, broadcast) permanece **exatamente igual** — o TLS age na camada do socket de forma transparente.

**Geração do certificado auto-assinado (roda uma vez):**
```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout key.pem -out cert.pem -subj "//CN=localhost"
```

**Servidor — `server.py:258`:** cria o contexto TLS e envolve cada conexão aceita:
```python
tls_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls_ctx.load_cert_chain("cert.pem", "key.pem")

raw_conn, addr = self.sock.accept()
conn = tls_ctx.wrap_socket(raw_conn, server_side=True)  # handshake TLS aqui
```

**Cliente — `client.py:186`:** envolve o socket após o `connect()`:
```python
tls_ctx = ssl.create_default_context()
tls_ctx.check_hostname = False   # necessário para cert auto-assinado
tls_ctx.verify_mode = ssl.CERT_NONE
self.sock = tls_ctx.wrap_socket(raw_sock)
```

**O que o TLS garante a partir disso:**
- **Confidencialidade** — tráfego cifrado com AES (ninguém lê com Wireshark)
- **Integridade** — TLS já inclui MAC internamente (o HMAC do envelope continua como camada extra)
- **Autenticidade** — o certificado prova que é o servidor correto

**Por que `check_hostname = False` e `CERT_NONE`?** O certificado foi auto-assinado para fins acadêmicos. Em produção, usaria um certificado emitido por uma CA confiável (ex: Let's Encrypt) e essas duas linhas seriam removidas.

---

## BÔNUS — Análise crítica: por que TLS e não HMAC ou RSA?

**HMAC-SHA256** garante integridade e autenticidade, mas as mensagens trafegam em texto puro — qualquer pessoa com Wireshark na rede leria os lances e senhas. Não é criptografia.

**RSA-4096 puro** também estaria errado para cifrar o tráfego: RSA é lento e tem limite de tamanho por operação (~500 bytes). Ele serve para **troca de chaves**, não para cifrar dados em fluxo. O correto seria RSA para trocar uma chave → AES-GCM para cifrar os dados — que é exatamente o que o TLS faz internamente.

**TLS** resolve os três requisitos de uma vez com a stdlib do Python:

| Propriedade | TLS implementado |
|---|---|
| Confidencialidade | ✅ tráfego cifrado com AES |
| Integridade | ✅ MAC interno do TLS |
| Autenticidade | ✅ certificado do servidor |

---

## Checklist rápido

| Requisito da prova | Onde |
|---|---|
| Socket TCP | `server.py:252` · `client.py:181` |
| Thread por cliente | `server.py:269` |
| Cadastrar item | `server.py:_add_item` |
| Receber/armazenar lances com autor | `server.py:_handle_bid` |
| Notificar compradores do lance | `server.py:broadcast` |
| Encerrar + notificar vencedor | `server.py:_close_item` |
| Validar lance > anterior | `server.py:416` |
| Interface do cliente (lances) | `client.py:repl` |
| Painel em tempo real | `client.py:listen_loop` |
| Persistência em arquivo | `server.py:_persist_item_locked` |
| **BÔNUS** Autenticação | `server.py:_try_auth` |
| **BÔNUS** Criptografia TLS | `server.py:258` · `client.py:186` |
