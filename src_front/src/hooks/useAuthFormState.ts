import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { me } from '../api/auth';
import { useAuthStore } from '../store/auth';

export function useAuthFormState() {
  const navigate = useNavigate();
  const setUser = useAuthStore((s) => s.setUser);
  const [apiError, setApiError] = useState<string | null>(null);

  const handleAuthAction = async (action: () => Promise<unknown>, fallback: string) => {
    setApiError(null);
    try {
      await action();
      const { data: user } = await me();
      setUser(user);
      navigate('/');
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
        fallback;
      setApiError(msg);
    }
  };

  return { apiError, handleAuthAction };
}
