# ADR 003: Independent paddock devices and replay

Phase 3 gives every existing stable paddock ID its own HA device. Shared weather
remains on the integration device; sensors and management controls use entry ID,
paddock ID and metric key as their unique identities. Renaming preserves identity.

Each paddock owns settings, an active growth cycle, archived cycles and versioned
daily results in HA Store. The Phase 2 schema receives additive defaults; prior
weather and observations are retained. Resets require explicit confirmation and
the current cycle ID, archive the old cycle and affect only the selected paddock.
The button requests confirmation without changing the cycle. Cycles freeze their
location/timezone; a new cycle adopts the current integration context.

Replay includes every date from cycle start, including gaps. Missing temperature,
daylength or compatible moisture blocks cumulative SPECHR until backfilled. Missing
radiation blocks WSC without inventing development inputs. Primary calculations
accept observed/provider-quality weather and an explicitly attested compatible
dimensionless soil index. Percent VWC is diagnostic, with no automatic conversion.
The moisture expression is deliberately unset until selected; scientific limitations
and the specification/paper discrepancy remain as recorded in ADR 001.

An opt-in scenario may use estimated weather and assumed wi, separate from primary
results. Changing assumptions replays the entire current scenario cycle and stores
new result versions. GDD is an independent diagnostic with configurable base, not
SPECHR. Enable/disable retains history. Management notes are not model inputs.

Local verification covers replay, gaps, changed inputs, restart persistence, additive
migration, independent confirmed resets, DST soil coverage and HA platform/device
contracts. These contracts use explicit HA doubles. Actual HA API tests are maintained
separately for Linux; they cannot run in the current Windows/Python 3.12 environment.
Phase 2 was loaded on the user's HA instance; Phase 3 requires a live upgrade check.
