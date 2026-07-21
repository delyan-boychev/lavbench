import { useQuery } from '@tanstack/react-query';
import api from '../services/ApiService';

export function useDocsQuery(tab, lang) {
  return useQuery({
    queryKey: ['docs', tab, lang],
    queryFn: async () => {
      const res = await api.fetch(`/api/docs/${tab}?lang=${lang}`, {
        headers: { 'Accept-Language': lang },
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to load docs');
      }
      return res.json();
    },
    enabled: !!tab && !!lang,
    staleTime: 60_000,
  });
}
