import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../lib/api';

interface AdminCheckResult {
  isAdmin: boolean;
  isLoading: boolean;
  role: string | null;
}

let adminCache: { wallet: string; isAdmin: boolean; role: string } | null = null;

export function clearAdminCache(): void {
  adminCache = null;
}

export function useAdminCheck(): AdminCheckResult {
  const { isAuthenticated, user } = useAuth();
  const [isAdmin, setIsAdmin] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated || !user?.wallet) {
      setIsAdmin(false);
      setRole(null);
      setIsLoading(false);
      adminCache = null;
      return;
    }

    setIsLoading(true);
    if (adminCache && adminCache.wallet === user.wallet) {
      setIsAdmin(adminCache.isAdmin);
      setRole(adminCache.role);
      setIsLoading(false);
      return;
    }

    api.checkAdmin()
      .then((result: { isAdmin: boolean; role: string | null }) => {
        setIsAdmin(result.isAdmin);
        setRole(result.role);
        adminCache = { wallet: user.wallet, isAdmin: result.isAdmin, role: result.role ?? '' };
      })
      .catch(() => {
        setIsAdmin(false);
        setRole(null);
        adminCache = null;
      })
      .finally(() => setIsLoading(false));
  }, [isAuthenticated, user?.wallet]);

  return { isAdmin, isLoading, role };
}
