-- Keep invite data and mutation RPCs behind the server boundary.
--
-- The public schema is exposed by Supabase's Data API. These tables and
-- functions are used only by the Boulder Roller backend with its server key;
-- browser roles must not be able to inspect, mint, edit, consume, or delete
-- invite state directly.

ALTER TABLE public.invite_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invite_code_usage ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.invite_codes FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.invite_code_usage FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.invite_codes TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.invite_code_usage TO service_role;

REVOKE ALL ON FUNCTION public.check_invite_code(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.consume_invite_code(TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.validate_invite_code(TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.check_invite_code(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.consume_invite_code(TEXT, TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.validate_invite_code(TEXT, TEXT, TEXT, TEXT) TO service_role;
