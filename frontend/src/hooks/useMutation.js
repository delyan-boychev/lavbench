import { useState, useCallback } from 'react';

export default function useMutation() {
  const [loadingMap, setLoadingMap] = useState({});

  const isLoading = useCallback((name) => !!loadingMap[name], [loadingMap]);

  const run = useCallback(async (name, fn) => {
    setLoadingMap((prev) => ({ ...prev, [name]: true }));
    try {
      return await fn();
    } finally {
      setLoadingMap((prev) => ({ ...prev, [name]: false }));
    }
  }, []);

  return { isLoading, run };
}
