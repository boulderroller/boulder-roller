-- Auto-generated from OSM data by seed_vault_from_osm.py
-- 8 canonical Philadelphia climbs


INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    'Waverly Road',
    'waverly-road',
    'Local climb in the Philadelphia area - 46m elevation gain',
    'Philadelphia',
    'US',
    40.0367874,
    40.0478948,
    -75.3023387,
    -75.2754879,
    105.8,
    118.3,
    46.5,
    0.1,
    9.6,
    2691.4,
    'ece59f325c2821b7db77737174afa3424422933b255d5588a901beba2ffc52174239e5ce3dcefa8e4528362800000285e91cd0def9fb85b95921162751cb8a5a',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    47.0,
    ARRAY['philadelphia', 'local', 'waverly']::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();


INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    'Harts Lane',
    'harts-lane',
    'Local climb in the Philadelphia area - 110m elevation gain',
    'Philadelphia',
    'US',
    40.0619822,
    40.0781158,
    -75.26980040000001,
    -75.2577789,
    81.0,
    115.4,
    109.9,
    3.0,
    13.1,
    2176.5,
    '6d2f054a229757605aa116167cd76832c6cce0fead0def3d7d543f65d7981f8042dbbf3940415d9745080737000002098750c0bb1335d08f317e24b9e3d9d781',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    142.9,
    ARRAY['philadelphia', 'local', 'harts']::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();


INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    'Manor Road',
    'manor-road',
    'Local climb in the Philadelphia area - 78m elevation gain',
    'Philadelphia',
    'US',
    40.0647625,
    40.0762858,
    -75.2604,
    -75.2472041,
    98.7,
    100.3,
    78.4,
    3.3,
    10.8,
    1757.7,
    '97605e1f9c1af7860c9a18e5bb7f30dbd9321e7ba8b7a915d8a2539e3efc36c8429cba844054eede44dbb581000001a543a33f06aedb56f2e5efa8df27935304',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    104.3,
    ARRAY['philadelphia', 'local', 'manor']::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();


INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    'Hollow Road',
    'hollow-road',
    'Local climb in the Philadelphia area - 92m elevation gain',
    'Philadelphia',
    'US',
    40.1309975,
    40.150466300000005,
    -75.4935956,
    -75.4778778,
    111.4,
    113.4,
    91.9,
    2.9,
    9.4,
    2746.3,
    '2eb79ab2fb7657dbb965dd48d663a971f678edd9682090029695537e63847ede42b7bdcc403c88b2452ba55b00000292a619c6fcd836415275a519e3ba247f09',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    118.6,
    ARRAY['philadelphia', 'local', 'hollow']::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();


INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    'Shurs Lane',
    'shurs-lane',
    'Local climb in the Philadelphia area - 30m elevation gain',
    'Philadelphia',
    'US',
    40.0246046,
    40.0269683,
    -75.2142243,
    -75.2094416,
    79.9,
    79.9,
    30.1,
    6.2,
    7.1,
    485.2,
    '1da21742ba75da802bf7162eb85f633f835777d346682356f3b8632af763bb1d41f130fc40c6d7bb43f2985b00000074f26ba3b42ae5e42c5d674f46efde384b',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    48.8,
    ARRAY['philadelphia', 'local', 'shurs']::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();


INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    'Arden Road',
    'arden-road',
    'Local climb in the Philadelphia area - 53m elevation gain',
    'Philadelphia',
    'US',
    40.0624714,
    40.0660856,
    -75.3576692,
    -75.3429718,
    97.8,
    97.8,
    53.0,
    3.9,
    8.2,
    1345.5,
    '3ab0d54b39f53f7ca02f440a5cdd68f1acf55b007afc20fcefe9cc7be5c0c8614253f2cf4079b72544a82f9700000142e8f97f4994453d9a5d30d86c63d0455c',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    73.7,
    ARRAY['philadelphia', 'local', 'arden']::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();


INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    'Old Gulph Road',
    'old-gulph-road',
    'Local climb in the Philadelphia area - 26m elevation gain',
    'Philadelphia',
    'US',
    40.0274676,
    40.032054800000004,
    -75.3031382,
    -75.287073,
    61.4,
    107.2,
    26.5,
    -1.6,
    12.4,
    1537.1,
    '60b14b631aa72a63e246b5a2b3bb5d53f7c610bc12bc095efd0234d7596ec97141d39d50bfcbf28244c022e100000170ca4ae46d2bd533358477dcf261f23a78',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    30.7,
    ARRAY['philadelphia', 'local', 'old-gulph']::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();


INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    'Welsh Valley Road',
    'welsh-valley-road',
    'Local climb in the Philadelphia area - 114m elevation gain',
    'Philadelphia',
    'US',
    40.079449000000004,
    40.087905,
    -75.480214,
    -75.474901,
    186.9,
    188.2,
    114.4,
    7.2,
    10.8,
    1562.0,
    '715c91af7cf71cc00efdad1423bae77886b6877681e532fc1d18f74d3cdb195e42e4c3d040e79b2644c33f8c0000017674e1fb20b5f224f6b6ccc700fad51457',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    196.8,
    ARRAY['philadelphia', 'local', 'welsh-valley']::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();
