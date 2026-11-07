-- Device testimony from ride files (FIT evidence pass): provenance rows
-- (head unit + sensors, held at full fidelity for personhood — never
-- rendered raw), the device's Session claims plus our recomputation and
-- the event-derived clock (the tripwire), and the weather source marker.
alter table rides add column if not exists device_provenance jsonb;
alter table rides add column if not exists device_summary jsonb;
alter table rides add column if not exists weather_source text;
