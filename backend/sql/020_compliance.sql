-- Worker E compliance schema

-- Audit log for significant operations
CREATE TABLE IF NOT EXISTS public.audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES public.users(id) ON DELETE SET NULL,
  action varchar(100) NOT NULL,
  target_type varchar(50),
  target_id uuid,
  metadata jsonb DEFAULT '{}'::jsonb,
  ip_address inet,
  user_agent text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user ON public.audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON public.audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON public.audit_log(created_at);

-- Data deletion requests
CREATE TABLE IF NOT EXISTS public.deletion_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id),
  wallet text NOT NULL,
  requested_at timestamptz DEFAULT now(),
  completed_at timestamptz,
  status varchar(20) DEFAULT 'pending',
  error_message text
);

CREATE INDEX IF NOT EXISTS idx_deletion_requests_status ON public.deletion_requests(status);

-- Data export requests
CREATE TABLE IF NOT EXISTS public.export_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id),
  requested_at timestamptz DEFAULT now(),
  completed_at timestamptz,
  download_url text,
  expires_at timestamptz,
  status varchar(20) DEFAULT 'pending'
);
