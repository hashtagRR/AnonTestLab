# Known limitations (v0.5)

Simplifications of this version, stated so that results are read with them in mind:

- **Fixed-size cells still leak hop position.** Cells are exactly `cell_size` bytes at hop 1 regardless of path length, but shrink by a fixed amount per hop *position* within a circuit. A single-link observer can't distinguish path lengths or real/cover/EXTEND from size alone, but a global observer watching multiple hops of the same circuit could infer hop depth from the size sequence (the `hop_depth` adversary measures exactly this).
- **Per-edge link conditions are directional-only.** `link_conditions.per_edge` scales a relay's forward-direction send to a specific peer and is directional: only the connection-initiating side is scaled (it always knows both endpoints locally); the receiving side's own upstream-facing sends on that connection still use its plain per-node value, since telling it would need a wire-protocol change this scope didn't take on.
- **No relay identity or directory system.** Keys are ephemeral only, so there's no TOFU question to answer, but also no persistent relay reputation.
- **Wave mode changes the timestamp origin.** With `sessions.max_concurrent`, each session's timestamps start at that session's own start, so flows from different waves line up as if concurrent. Without it, all sessions share the experiment clock.
- **The `latency` split policy uses nominal RTTs.** Legs are not given different real latencies; only the scheduling decision follows the configured RTTs.
- **`bandwidth_weighted` routing doesn't model guard/exit-flag constraints.** It selects without replacement in proportion to each node's configured weight and leaves out Tor's position rules on purpose.
- **Timing varies run to run.** The experiment *design* (path choices, traffic schedule) is reproducible from the seed, but real measured latency and timing will vary like any real system's would, since sessions run concurrently over real sockets and each relay subprocess has its own independent random state for loss/drop/watermark rolls.
