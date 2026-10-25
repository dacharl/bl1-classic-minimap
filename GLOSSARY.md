# Classic minimap diagnostics

Language for the playable minimap, how it coexists with other HUD mods, and its optional performance investigation tools.

## Language

**Standard minimap artifact**:
The minimap release for ordinary play, without performance data collection.
_Avoid_: Timing-disabled build, profiler build

**Profiler add-on**:
An optional companion to the standard minimap that measures minimap operations during investigation.
_Avoid_: Instrumented minimap, external process

**Profiling distribution**:
A separate investigation download containing the unchanged standard minimap artifact plus the profiler add-on.
_Avoid_: Debug build, instrumented release

**Performance capture**:
A deliberately started, bounded period of minimap performance observation.
_Avoid_: Report, session dump

**Performance report**:
Saved evidence from a performance capture, including measurements, context and limitations.
_Avoid_: Capture, live state

**Admitted update**:
A minimap tick that passes the 0.05 s throttle and does work, as opposed to one that returns at the throttle.
_Avoid_: Frame, tick (unqualified)

**Detach conflict**:
The state where another mod replaced a function after the profiler add-on wrapped it, so detaching cannot restore a clean call path.
_Avoid_: Partial detach, failed detach

**Unsupported lifecycle**:
A capture outcome recorded when the core minimap module is reloaded while the profiler add-on is attached.
_Avoid_: Crash, reset

**Report contract**:
The frozen performance report schema plus fixture reports that this repository publishes and the MCP performance adapter is built against.
_Avoid_: API, interface (unqualified)

**Foreign HUD movie**:
A HUD movie that another mod has put into the HUD movie template, neither the stock HUD nor ours.
_Avoid_: Modded HUD, other HUD (unqualified)

**Minimap block**:
The tags our build inserts before stock's first `ShowFrame`: the minimap's characters, exports and root functions.
_Avoid_: Patch, diff

**Block manifest**:
The facts shipped with the minimap block that a merge checks: stock's prefix tag codes, our gradient count and our character id range.
_Avoid_: Metadata (unqualified)

**Stock prefix**:
The top-level tags before the first `ShowFrame` in the stock classic HUD movie; a foreign HUD movie must have the same tag codes there to be merged.
_Avoid_: Header

**Merged HUD movie**:
A foreign HUD movie with the minimap block spliced in at runtime, installed as a new movie object the template points at.
_Avoid_: Combined build, patched HUD

**Merge refusal**:
The outcome when a foreign HUD movie fails a structural check: the other mod keeps the template and the minimap stays idle with a message.
_Avoid_: Merge failure, conflict

**MCP performance adapter**:
The diagnostic reader that turns a saved minimap performance report into validated, inspectable evidence.
_Avoid_: Profiler, collector
