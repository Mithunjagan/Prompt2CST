# Capability registry

The capability registry describes compiler reality rather than an antenna
catalog. Every entry records its ID, support status, required parameters,
validator, compiler, CST versions, limitations, closest supported alternative,
and whether an extension can add it.

The desktop capability browser and `antenna_catalog` MCP tool expose this same
registry. Planning compares the requested DesignIR against it. A missing
capability is a blocking error that names the exact feature, closest
alternative, and extension possibility. Prompt2CST never silently substitutes
a different antenna topology.

Existing antenna families remain compatibility templates. They are not a
closed list of possible designs.
