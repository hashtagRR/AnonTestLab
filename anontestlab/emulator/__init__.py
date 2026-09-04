"""Real localhost network emulator: relay nodes run as separate OS
processes bound to real 127.0.0.1:<port> sockets, connected by a
telescoping (Tor-style) onion circuit with genuine per-hop AEAD
encryption. This is the primary engine for traffic/latency/correlation
experiments; `anontestlab.core` (the discrete-event simulator) stays around
only as a fast, transport-free utility for Monte Carlo/statistical
adversaries and sweeps."""
