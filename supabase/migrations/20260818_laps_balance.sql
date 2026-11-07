-- Device laps (the rider's own segmentation) and power balance summary.
alter table rides add column if not exists laps jsonb;
alter table rides add column if not exists power_balance jsonb;
