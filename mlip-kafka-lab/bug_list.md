# Frequent bugs and solutions

### `NoBrokersAvailable`

```
NoBrokersAvailable: NoBrokersAvailable
```

You are not connected to the server. Open the SSH tunnel first and leave it running:

```
ssh -o ServerAliveInterval=60 -L 9092:localhost:9092 <NetID>@cs544-f26.cs.uic.edu -NTf
```

### `Broker transport failure` when running kcat

```
running:  kcat -b localhost:9092 -t recitation-c -C -o earliest
%3|1725369171.734|FAIL|rdkafka#consumer-1| [thrd:localhost:9092/bootstrap]: localhost:9092/bootstrap: Connect to ipv6#[::1]:9092 failed: Connection refused (after 1ms in state CONNECT)
% ERROR: Failed to query metadata for topic recitation-c: Local: Broker transport failure
```

`kcat` talks to the broker through the same tunnel as the notebook. You still need to connect to the server first by running:

```
ssh -o ServerAliveInterval=60 -L 9092:localhost:9092 <NetID>@cs544-f26.cs.uic.edu -NTf
```

### Port 9092 already in use

If the tunnel fails because the local port is taken, close the old tunnel and open a new one:

```
lsof -ti:9092 | xargs kill -9
```

### Windows users

Run the SSH tunnel, `kcat`, and the notebook from the same environment. If you use WSL, open the tunnel inside your WSL (Ubuntu) shell rather than in PowerShell, otherwise `localhost:9092` will not resolve to the tunnel from inside WSL.
