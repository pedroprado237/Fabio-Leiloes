# Plataforma Distribuída de Leilões — Guia de Uso

Sistema cliente/servidor em Python que permite que múltiplos compradores se conectem a um servidor central, recebam atualizações em tempo real de itens e lances, e disputem um leilão. Este documento explica o funcionamento de cada parte do código e como rodar e testar a aplicação.

---

## 1. Requisitos

- **Python 3.10+** (usa `dict[...]`, `list[...]`, `str | None` — sintaxe PEP 604 e PEP 585). Testado em Python 3.13.
- **Somente biblioteca padrão**: `socket`, `threading`, `json`, `hashlib`, `hmac`, `getpass`, `datetime`, `os`, `sys`. Não precisa instalar nada via `pip`.
- Rede TCP entre as máquinas (porta padrão **5000** aberta no firewall da máquina servidora).

Arquivos entregues:

```
Leilao/
├── server.py     # servidor do leilão
├── client.py     # cliente (comprador)
└── Uso.md        # este arquivo
```

Arquivo gerado em tempo de execução:

```
auction_history.log   # histórico persistido (JSON-lines), criado pelo servidor
```

---

## 2. Como rodar

### 2.1 Rodando tudo localmente (mesma máquina)

Abra **três terminais** no diretório `C:\Users\Pedro\Documents\Projects\Leilao`.

**Terminal 1 — servidor:**

```bash
python server.py
# ou com porta customizada:
python server.py 5000
```

**Terminais 2 e 3 — clientes (compradores):**

```bash
python client.py 127.0.0.1 5000
```

Cada cliente vai pedir `usuário` e `senha`. Use qualquer combinação da tabela abaixo.

### 2.2 Rodando em rede (máquinas diferentes)

1. Descubra o IP da máquina que vai rodar o servidor (ex: `ipconfig` no Windows → IPv4 `192.168.0.42`).
2. Garanta que a porta 5000/TCP está liberada no firewall do Windows Defender.
3. No servidor:

   ```bash
   python server.py 5000
   ```

   O servidor faz `bind` em `0.0.0.0`, então aceita conexões de qualquer IP.
4. Em cada máquina cliente:

   ```bash
   python client.py 192.168.0.42 5000
   ```

### 2.3 Usuários pré-cadastrados

| Usuário                    | Senha      |
|----------------------------|------------|
| Shaolin_Matador_de_Porco   | senha123   |
| Pedrin_do_Pneu             | senha456   |
| JP_Tintas                  | senha789   |
| Breu_Autopeças             | senha654   |
| admin                      | admin      |

Os hashes estão no dicionário `USERS` de `server.py`. Para adicionar um usuário novo, inclua a linha `"novo_usuario": hashlib.sha256(b"nova_senha").hexdigest(),`.

---

## 3. Roteiro de teste (passo a passo)

O objetivo é exercitar **todos os requisitos** do enunciado em um único fluxo.

### Cenário

- 1 servidor (console admin)
- 2 compradores: `Pedrin_do_Pneu` e `JP_Tintas`
- 1 item: "iPhone 15", lance inicial R$ 1000,00

### Passos

1. **Iniciar servidor** (Terminal 1):
   ```
   python server.py 5000
   ```
   Saída esperada:
   ```
   [SERVER] Escutando em 0.0.0.0:5000

   Comandos: add <nome...> <lance_inicial> | close <id> | list | quit

   admin>
   ```

2. **Conectar Pedrin_do_Pneu** (Terminal 2):
   ```
   python client.py 127.0.0.1 5000
   usuário: Pedrin_do_Pneu
   senha: senha456
   ```
   Saída esperada:
   ```
   [OK] autenticado como Pedrin_do_Pneu

   === estado do leilão ===
     (sem itens)
   >
   ```

3. **Conectar JP_Tintas** (Terminal 3): igual ao passo 2, com `JP_Tintas / senha789`.

4. **Cadastrar item no admin**:
   ```
   admin> add iPhone 15 1000
   ```
   Servidor mostra `[SERVER] item #1 'iPhone 15' cadastrado (lance inicial R$ 1000.00)`. Os dois clientes recebem automaticamente:
   ```
   [NOVO ITEM] #1 'iPhone 15' (lance inicial R$ 1000.00)
   ```

5. **Pedrin_do_Pneu dá o primeiro lance**:
   ```
   > bid 1 1200
   ```
   Ambos os clientes (inclusive Pedrin_do_Pneu) recebem:
   ```
   [NOVO LANCE] item #1 'iPhone 15': R$ 1200.00 por Pedrin_do_Pneu
   ```

6. **JP_Tintas tenta dar um lance menor** (deve falhar):
   ```
   > bid 1 800
   ```
   JP_Tintas recebe:
   ```
   [ERRO] lance deve ser maior que o atual (R$ 1200.00)
   ```
   Pedrin_do_Pneu não recebe nada — o lance foi rejeitado antes do broadcast.

7. **JP_Tintas cobre o lance**:
   ```
   > bid 1 1500
   ```
   Ambos recebem `[NOVO LANCE] ... R$ 1500.00 por JP_Tintas`.

8. **Listar estado em um cliente**:
   ```
   > list
   ```
   Resposta:
   ```
   === estado do leilão ===
     #1 [aberto] iPhone 15: R$ 1500.00 (JP_Tintas)
   ```

9. **Encerrar no admin**:
   ```
   admin> close 1
   ```
   Ambos os clientes recebem:
   ```
   [ENCERRADO] item #1 'iPhone 15' — vencedor: JP_Tintas (R$ 1500.00)
   ```

10. **Verificar persistência**: abra `auction_history.log` na pasta do servidor. Deve haver uma linha JSON com o item, histórico de lances, datas e vencedor.

11. **Testar credenciais inválidas**: abra um quarto cliente com senha errada. Ele recebe `[FALHA] credenciais inválidas` e a conexão é fechada.

12. **Encerrar servidor**:
    ```
    admin> quit
    ```

### Checklist contra os requisitos do enunciado

- [x] Comunicação via sockets TCP.
- [x] Gerenciamento de threads para conexões concorrentes.
- [x] Gerenciar estado do leilão (item, lance atual).
- [x] Cadastrar item (`add`).
- [x] Receber e armazenar lances identificando o autor.
- [x] Ao receber um lance, informar compradores do lance atual (autor + valor).
- [x] Encerrar leilão (`close`) notificando todos com vencedor e valor.
- [x] Validar lances (lance > atual).
- [x] Notificar todos os participantes sobre novos lances.
- [x] Cliente: conexão, interface para lances, painel em tempo real.
- [x] Persistência em arquivo (`auction_history.log`).
- [x] Bônus — autenticação por usuário/senha.
- [x] Bônus — integridade das mensagens via HMAC-SHA256 (camada sobre a qual é trivial ativar TLS via `ssl.wrap_socket`).

---

## 4. Arquitetura

```
+---------------+                               +----------------+
|  Console      |                               |  Cliente 1     |
|  admin (main  |                               |  (alice)       |
|  thread)      |                               +-------+--------+
+-------+-------+                                       |
        |                                               | TCP
        |                                               |
+-------v---------------------------------------+       |
|                 Servidor (AuctionServer)      |       |
|  +------------------+   +------------------+  |       |
|  | accept() loop    |   | state:           |  |       |
|  | (main thread)    |   |   items          |<---+----+
|  +---------+--------+   |   clients        |  | |
|            |            |   next_id        |  | |
|  +---------v--------+   +--------+---------+  | |
|  | thread por       |            |            | |
|  | cliente          |   Lock protege estado   | |
|  | handle_client()  |                         | |
|  +------------------+                         | |
|                                               | |
+-----------------------------------------------+ |
                                                  |
                                          +-------+--------+
                                          |  Cliente 2     |
                                          |  (bob)         |
                                          +----------------+
```

- **1 thread para `accept()`** (thread principal do servidor, dentro de `start()`).
- **1 thread daemon para o console admin** (`admin_console`), roda em paralelo ao `accept`.
- **1 thread por cliente** (`handle_client`). Cada thread tem seu próprio buffer de leitura e chama `send_json`/`broadcast`.
- **Um único `threading.Lock`** protege o estado compartilhado (`items`, `clients`, `next_id`). Todas as mutações e leituras críticas acontecem dentro de `with self.lock:`.
- O `broadcast` **copia** a lista de conexões dentro do lock e **envia fora do lock**, para não serializar o envio de rede.
- No cliente existe uma **thread de escuta** (`listen_loop`) que lê do socket e imprime notificações, enquanto a thread principal lê `input()` do usuário e envia comandos.

---

## 5. Protocolo de mensagens

Todas as mensagens são **JSON por linha (`\n` como delimitador)** sobre TCP. Cada mensagem vai dentro de um **envelope assinado**:

```json
{ "sig": "<HMAC-SHA256 do body em hex>", "body": "<string JSON>" }
```

O receptor:
1. Faz `json.loads` do envelope.
2. Recomputa o HMAC de `body` com a mesma chave pré-compartilhada (`SHARED_HMAC_KEY`).
3. Compara com `sig` usando `hmac.compare_digest` (resistente a timing attacks).
4. Se bater, faz `json.loads(body)` e processa. Se não bater, descarta.

Isso garante **integridade e autenticidade** das mensagens. A chave está hardcoded nos dois arquivos (`server.py` e `client.py`) — em produção viria de variável de ambiente ou handshake Diffie-Hellman, e a gente usaria TLS para ter também confidencialidade.

### Mensagens cliente → servidor

| `type` | Campos                                    | Descrição                            |
|--------|-------------------------------------------|--------------------------------------|
| `auth` | `user`, `password`                        | Autentica. Deve ser a primeira msg.  |
| `bid`  | `item_id` (int), `value` (float)          | Envia um lance.                      |
| `list` | —                                         | Solicita o estado atual.             |

### Mensagens servidor → cliente

| `type`        | Campos                                                           |
|---------------|------------------------------------------------------------------|
| `auth_ok`     | `user`                                                           |
| `auth_fail`   | `message`                                                        |
| `state`       | `items`: lista com `{item_id, name, current_bid, bidder, open}`  |
| `item_added`  | `item_id`, `name`, `starting`                                    |
| `new_bid`     | `item_id`, `name`, `bidder`, `value`                             |
| `item_closed` | `item_id`, `name`, `winner` (ou `null`), `value`                 |
| `error`       | `message`                                                        |

---

## 6. Código explicado — `server.py`

### 6.1 Importações e constantes

```python
import hashlib, hmac, json, os, socket, sys, threading
from datetime import datetime

HOST = "0.0.0.0"
DEFAULT_PORT = 5000
HISTORY_FILE = "auction_history.log"
```

- `socket` + `threading`: base da comunicação concorrente.
- `hashlib`/`hmac`: hash de senha (SHA-256) e assinatura de mensagens (HMAC).
- `json`: serialização do protocolo.
- `datetime`: timestamps ISO-8601 no histórico.

### 6.2 Tabela de usuários e chave HMAC

```python
USERS = {
    "alice": hashlib.sha256(b"senha123").hexdigest(),
    ...
}
SHARED_HMAC_KEY = b"leilao-shared-hmac-key-2026"
```

- Senhas **nunca** são armazenadas em claro; apenas o hash SHA-256 fica em memória.
- A chave HMAC é simétrica e precisa ser igual nos dois lados.

### 6.3 Funções `sign` / `verify`

```python
def sign(payload: bytes) -> str:
    return hmac.new(SHARED_HMAC_KEY, payload, hashlib.sha256).hexdigest()

def verify(payload: bytes, tag: str) -> bool:
    return hmac.compare_digest(sign(payload), tag or "")
```

`compare_digest` evita vazamento por timing. Se qualquer byte do `body` for alterado em trânsito, o HMAC não bate e a mensagem é descartada.

### 6.4 Classe `AuctionServer`

#### Estado

```python
self.items: dict[int, dict] = {}  # item_id -> metadados do item
self.next_id = 1                  # gerador de IDs sequenciais
self.clients: dict[socket, dict]  # conn -> {user, addr}
self.lock = threading.Lock()      # mutex único para estado compartilhado
self.running = True
```

Cada item tem:
```python
{
    "name": str,
    "starting": float,          # lance inicial
    "current_bid": float,       # lance atual (= maior recebido)
    "bidder": str | None,       # nome do autor do maior lance
    "open": bool,               # True enquanto o leilão está rolando
    "history": list[dict],      # [{time, bidder, value}, ...]
    "created_at": str,          # ISO timestamp
    "closed_at": str (quando fechar)
}
```

#### `start()` — aceita conexões

```python
self.sock = socket.socket(AF_INET, SOCK_STREAM)
self.sock.setsockopt(SO_REUSEADDR, 1)
self.sock.bind((self.host, self.port))
self.sock.listen(32)
threading.Thread(target=self.admin_console, daemon=True).start()

while self.running:
    conn, addr = self.sock.accept()
    conn.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
    threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
```

- `SO_REUSEADDR` evita "Address already in use" ao reiniciar.
- `TCP_NODELAY` desliga o algoritmo de Nagle — como trocamos mensagens pequenas (JSON de poucas centenas de bytes), queremos latência baixa.
- Cada cliente aceita é isolado em uma thread daemon (morre quando o processo morre).

#### `send_json()` — empacota em envelope HMAC

```python
body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
tag = sign(body)
envelope = {"sig": tag, "body": body.decode("utf-8")}
data = (json.dumps(envelope) + "\n").encode("utf-8")
conn.sendall(data)
```

`ensure_ascii=False` permite acentos (ex: "não") sem escape.

#### `broadcast()` — entrega para todos os conectados

```python
with self.lock:
    targets = [c for c in self.clients if c is not exclude]
for c in targets:
    self.send_json(c, obj)
```

Chave da implementação: **copiar a lista dentro do lock e enviar fora**, para que um cliente lento não bloqueie outro.

#### `handle_client()` — ciclo de vida de cada conexão

```python
while self.running:
    chunk = conn.recv(4096)
    if not chunk: break
    buf += chunk
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        msg = self._parse_envelope(line)
        if user is None:
            user = self._try_auth(conn, addr, msg)
        else:
            self._dispatch(conn, user, msg)
```

- Buffer por conexão — TCP não preserva "mensagem", só bytes. O delimitador `\n` define o fim de cada mensagem.
- A variável local `user` é o "estado" de autenticação: antes de autenticar, só a mensagem `auth` é processada.

#### `_try_auth()` — autenticação

```python
got = hashlib.sha256(password.encode("utf-8")).hexdigest()
if not expected or not hmac.compare_digest(expected, got):
    self.send_json(conn, {"type": "auth_fail", ...})
    return None
self.clients[conn] = {"user": u, "addr": addr}
self.send_json(conn, {"type": "auth_ok", "user": u})
self._send_state(conn)
```

Depois de autenticar, o cliente é **registrado no dicionário `self.clients`**, que é o que o `broadcast` usa.

#### `_handle_bid()` — validação e broadcast

```python
with self.lock:
    it = self.items.get(item_id)
    if not it: return error("item não encontrado")
    if not it["open"]: return error("leilão encerrado")
    if value <= it["current_bid"]: return error("lance deve ser maior")
    it["current_bid"] = value
    it["bidder"] = user
    it["history"].append({"time": ..., "bidder": user, "value": value})
    payload = {"type": "new_bid", ...}
self.broadcast(payload)
```

**Toda** a validação e a atualização do estado acontece sob o lock, garantindo que dois lances concorrentes não "colidam" (o segundo vai ver o estado já atualizado pelo primeiro).

#### Comandos do admin — `_add_item` / `_close_item`

- `_add_item`: gera ID sequencial, cria o registro, faz broadcast `item_added`.
- `_close_item`: marca `open=False`, grava no log, faz broadcast `item_closed` com o vencedor.

#### `_persist_item_locked()` — persistência

```python
record = {
    "item_id": iid, "name": ..., "starting": ...,
    "final_value": item["current_bid"],
    "winner": item["bidder"],
    "created_at": ..., "closed_at": ...,
    "history": item["history"],
}
with open(HISTORY_FILE, "a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

Formato **JSON-lines**: cada linha é um registro de item encerrado, fácil de ler com qualquer ferramenta (`jq`, `pandas.read_json(lines=True)`, etc.).

#### `shutdown()`

Encerra todos os leilões abertos, persiste cada um, fecha conexões e fecha o socket de escuta.

### 6.5 `main()`

```python
port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
server = AuctionServer(HOST, port)
server.start()
```

---

## 7. Código explicado — `client.py`

### 7.1 Classe `AuctionClient`

Mesma ideia do servidor, mas com só uma conexão e duas threads:

- **Thread principal** (`repl`): lê `input()` e envia comandos.
- **Thread de escuta** (`listen_loop`): fica bloqueada em `recv()` e imprime notificações à medida que chegam.

### 7.2 `connect()`

```python
self.sock = socket.socket(AF_INET, SOCK_STREAM)
self.sock.connect((self.host, self.port))
self.sock.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
```

### 7.3 `send_json()` / `recv_message()`

Mesma lógica do servidor: monta envelope `{sig, body}`, assina, envia. Ao receber, verifica a assinatura antes de desserializar o body.

### 7.4 `authenticate()`

```python
self.send_json({"type": "auth", "user": user, "password": password})
msg = self.recv_message()
if msg.get("type") == "auth_ok":
    return True
```

Chamada uma única vez **antes** de iniciar a thread de escuta — por isso o buffer `self.buf` é acessado sem race (só uma thread está lendo por vez nesse ponto).

### 7.5 `listen_loop()` e `_render()`

Lê mensagens em loop e formata cada tipo:

- `new_bid` → `[NOVO LANCE] item #N 'nome': R$ X por fulano`
- `item_added` → `[NOVO ITEM] #N 'nome' (lance inicial R$ X)`
- `item_closed` → `[ENCERRADO] item #N 'nome' — vencedor: fulano (R$ X)`
- `state` → lista completa
- `error` → mensagem de erro

O `print_lock` (`threading.Lock`) envolve cada escrita em `stdout` para evitar que a thread de escuta e a thread principal escrevam ao mesmo tempo e embaralhem a saída.

### 7.6 `repl()` — REPL do usuário

```python
while self.running:
    line = input().strip()
    parts = line.split()
    cmd = parts[0].lower()
    if cmd == "bid":
        ...
        self.send_json({"type": "bid", "item_id": iid, "value": val})
    elif cmd == "list":
        self.send_json({"type": "list"})
    elif cmd == "quit":
        self.running = False
        break
```

`val = float(parts[2].replace(",", "."))` aceita tanto `1500.00` quanto `1500,00`.

### 7.7 `main()`

1. Lê host/porta dos argumentos.
2. Pede usuário via `input()` e senha via `getpass.getpass()` (não aparece na tela).
3. Conecta, autentica, dispara thread de escuta, entra no REPL.

---

## 8. Concorrência — por que isso é seguro

- **Estado global protegido por `Lock`**: todo acesso a `items`, `clients`, `next_id` acontece dentro de `with self.lock:`.
- **Validação de lance atômica**: comparar com `current_bid` e atualizar estão na mesma região crítica — não há "lost update".
- **Leitura de rede concorrente**: cada thread tem seu próprio `buf` local (parâmetro da função). Não há buffer compartilhado.
- **Escrita de rede**: `socket.sendall` é thread-safe desde que dois threads não escrevam no **mesmo** socket simultaneamente. Como só o `broadcast`/`send_json` escreve nos sockets dos clientes, e eles são chamados sequencialmente sobre cada socket, está OK. (Se houvesse outra fonte de escrita, faríamos um lock por conexão.)
- **Console admin** roda em thread separada do `accept()` — os dois nunca se atrapalham.

---

## 9. Persistência — formato do `auction_history.log`

Exemplo de uma linha após encerrar o iPhone 15:

```json
{"item_id": 1, "name": "iPhone 15", "starting": 1000.0, "final_value": 1500.0, "winner": "JP_Tintas", "created_at": "2026-04-17T14:21:03.512Z", "closed_at": "2026-04-17T14:22:55.117Z", "history": [{"time": "2026-04-17T14:21:30.001Z", "bidder": "Pedrin_do_Pneu", "value": 1200.0}, {"time": "2026-04-17T14:22:10.442Z", "bidder": "JP_Tintas", "value": 1500.0}]}
```

Para ler de forma amigável:

```bash
python -c "import json; [print(json.dumps(json.loads(l), indent=2, ensure_ascii=False)) for l in open('auction_history.log', encoding='utf-8')]"
```

---

## 10. Bônus — segurança

### 10.1 Autenticação

- Senhas armazenadas como **SHA-256** (função `USERS`).
- Comparação com `hmac.compare_digest` (tempo constante).
- Antes da primeira mensagem `auth` válida, qualquer outra mensagem recebe erro e não é processada.
- Falha de autenticação fecha a conexão.

### 10.2 Integridade (HMAC-SHA256)

- Todo JSON trafega dentro de um envelope `{sig, body}`.
- `sig = HMAC(SHARED_HMAC_KEY, body)`.
- Se um atacante alterar o `body`, o HMAC não bate e a mensagem é descartada silenciosamente.
- `hmac.compare_digest` usado para evitar timing attacks.

### 10.3 Criptografia completa (opcional — TLS)

Para adicionar confidencialidade, basta envolver os sockets com TLS:

**Servidor:**
```python
import ssl
ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ctx.load_cert_chain("cert.pem", "key.pem")
self.sock = ctx.wrap_socket(self.sock, server_side=True)
```

**Cliente:**
```python
ctx = ssl.create_default_context()
ctx.check_hostname = False  # só para cert self-signed
ctx.verify_mode = ssl.CERT_NONE
self.sock = ctx.wrap_socket(self.sock, server_hostname=host)
```

Gerando cert self-signed:
```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout key.pem -out cert.pem -subj "/CN=localhost"
```

Não está habilitado por padrão porque o enunciado é acadêmico e queremos zero dependência externa.

---

## 11. Solução de problemas

| Sintoma                                              | Causa provável / solução                                                                     |
|------------------------------------------------------|----------------------------------------------------------------------------------------------|
| `ConnectionRefusedError: [WinError 10061]`           | Servidor não está rodando ou porta diferente.                                                |
| Cliente em outra máquina não conecta                 | Firewall do Windows bloqueando. Liberar a porta 5000/TCP ou usar `netsh advfirewall`.        |
| `[FALHA] credenciais inválidas`                      | Usuário/senha errado. Ver tabela na seção 2.3.                                               |
| `lance deve ser maior que o atual`                   | Lance enviado <= `current_bid`. Use um valor maior.                                          |
| Mensagens aparecem "cortadas" na tela                | Normal: a thread de escuta imprime notificações enquanto você digita. Aperte Enter.          |
| Servidor não fecha com Ctrl+C                        | Use `quit` no prompt `admin>`.                                                                |
| `auction_history.log` vazio                          | Só é gravado **ao encerrar** um item (`close <id>`) ou no `quit` do servidor.                |

---

## 12. Comandos de referência rápida

**Servidor:**

```
python server.py [porta]         # inicia
admin> add <nome...> <inicial>   # cadastra item
admin> close <item_id>           # encerra leilão
admin> list                      # lista itens
admin> quit                      # encerra servidor
```

**Cliente:**

```
python client.py [host] [porta]  # conecta
> bid <item_id> <valor>          # envia lance
> list                           # pede estado
> quit                           # sai
```
