import { useCallback, useEffect, useRef } from 'react';
import type { NavigationGuard } from '../../shared/games';

/** A single active task owns draft confirmation; navigation never owns its save. */
export function useNavigationGuard() {
  const guard = useRef<NavigationGuard | null>(null);
  const register = useCallback((value: NavigationGuard | null) => { guard.current = value; }, []);
  const request = useCallback((proceed: () => void) => {
    if (guard.current) guard.current(proceed); else proceed();
  }, []);
  const hasPending = useCallback(() => guard.current !== null, []);
  const getRecovery = useCallback(() => guard.current?.recovery, []);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!guard.current) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, []);
  return { register, request, hasPending, getRecovery };
}
