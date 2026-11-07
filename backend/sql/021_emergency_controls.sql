-- Worker E emergency controls schema

CREATE TABLE IF NOT EXISTS public.system_controls (
  key varchar(100) PRIMARY KEY,
  value jsonb NOT NULL,
  updated_at timestamptz DEFAULT now(),
  updated_by uuid REFERENCES public.users(id)
);

INSERT INTO public.system_controls (key, value) VALUES
  ('staking_enabled', '{"enabled": true, "reason": null}'::jsonb),
  ('minting_enabled', '{"enabled": true, "reason": null}'::jsonb),
  ('uploads_enabled', '{"enabled": true, "reason": null}'::jsonb),
  ('withdrawals_enabled', '{"enabled": true, "reason": null}'::jsonb),
  ('maintenance_mode', '{"enabled": false, "message": null}'::jsonb)
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.admin_users (
  user_id uuid PRIMARY KEY REFERENCES public.users(id),
  role varchar(50) NOT NULL DEFAULT 'admin',
  granted_at timestamptz DEFAULT now(),
  granted_by uuid REFERENCES public.users(id)
);

CREATE INDEX IF NOT EXISTS idx_admin_users_role ON public.admin_users(role);
