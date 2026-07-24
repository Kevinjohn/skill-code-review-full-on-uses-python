"""Shared version-2 policy constants."""

TIER_A_REASON_CODES = {
    "durability_recovery",
    "migration_backup_restore",
    "isolation_shared_mutation",
    "unsafe_concurrent_code",
    "identity_permission_boundary",
    "secret_tenant_boundary",
    "untrusted_parsing",
    "consensus_replication",
    "public_compatibility",
    "destructive_administration",
    "external_acknowledgement",
    "central_high_fanout_control",
    "complex_material_behavior",
}

CAPSULE_LIST_FIELDS = (
    "entryPoints",
    "publicBoundaries",
    "dependencySeams",
    "importantCallersCallees",
    "tests",
    "documentation",
    "configuration",
    "commands",
    "sharedInvariants",
    "failureBoundaries",
    "evidenceLocations",
)
CAPSULE_SHARED_FIELDS = CAPSULE_LIST_FIELDS

TIER_A_DENSITY_DIAGNOSTIC = "PILOT-TIER-A-DENSITY"
TIER_A_DENSITY_MIN_UNITS = 5
TIER_A_DENSITY_THRESHOLD = 0.4
WARM_BATCH_MAX_ASSIGNMENTS = 5
CAPSULE_BYTE_WARNING = 32 * 1024
PACKET_BYTE_WARNING = 128 * 1024
