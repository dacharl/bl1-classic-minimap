# Keep profiling outside the standard minimap

The standard minimap artifact must incur no telemetry branches or instrumentation cost during ordinary play. Use a separate removable in-process profiler add-on and reuse the exact standard artifact in the profiling distribution, accepting that reversible wrappers provide narrower attribution than instrumentation inside the core. Validate actual gameplay impact with independent frame-time measurements; wrapper timings alone do not establish FPS loss.
