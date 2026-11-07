-- Ride depth fields: perceived exertion (rider-entered) and display-only
-- weather captured at processing time (effort-integrity co-signing stays
-- dropped; these are facts for the ride page, never inputs to CAL).
alter table rides add column if not exists perceived_exertion smallint
    check (perceived_exertion between 1 and 10);
alter table rides add column if not exists weather_temp_c real;
alter table rides add column if not exists weather_wind_mps real;
alter table rides add column if not exists weather_wind_deg smallint;
