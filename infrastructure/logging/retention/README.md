# Retention

`retention.sql` provides safe defaults. Production should run it from a controlled scheduled job after cold-storage export succeeds. Tenant plan overrides should be recorded in a separate retention-policy table before deleting data.
