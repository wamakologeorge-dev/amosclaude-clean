-- Default retention. Run from a scheduled job and customize per tenant plan.
DELETE FROM logs WHERE level IN ('TRACE', 'DEBUG') AND timestamp < now() - interval '30 days';
DELETE FROM logs WHERE level = 'INFO' AND timestamp < now() - interval '90 days';
DELETE FROM logs WHERE level = 'WARNING' AND timestamp < now() - interval '180 days';
DELETE FROM logs WHERE level IN ('ERROR', 'CRITICAL') AND timestamp < now() - interval '365 days';
