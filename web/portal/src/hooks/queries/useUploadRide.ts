import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';

export function useUploadRide() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => api.uploadRide(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.rides.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.threshold.all });
    },
  });
}
