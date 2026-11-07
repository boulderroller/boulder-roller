import { useQuery } from '@tanstack/react-query';
import { api, FitnessMetrics, PowerCurve, RidingDays, TrainingLoad, type TrainingModelSnapshot } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';

export interface TrainingDataResponse {
  snapshot: TrainingModelSnapshot | null;
  fitnessMetrics: FitnessMetrics;
  trainingLoad: TrainingLoad;
}

export function useTrainingData(days: number = 28) {
  return useQuery<TrainingDataResponse>({
    queryKey: queryKeys.analytics.trainingData(days),
    queryFn: async () => {
      const [fitnessMetrics, trainingLoad] = await Promise.all([
        api.getFitnessMetrics(),
        api.getTrainingLoad(days),
      ]);

      if (
        fitnessMetrics.thresholdVersion !== trainingLoad.thresholdVersion
        || fitnessMetrics.thresholdState !== trainingLoad.thresholdState
        || fitnessMetrics.thresholdTrainingState !== trainingLoad.thresholdTrainingState
      ) {
        throw new Error('Could not load training');
      }

      const candidate = (trainingLoad as TrainingLoad & { snapshot?: TrainingModelSnapshot }).snapshot;
      const snapshot = candidate?.revision?.trim() && Number.isFinite(Date.parse(candidate.asOf))
        && ['initialized', 'initializing'].includes(candidate.initialization)
        && ['complete', 'partial'].includes(candidate.coverage?.completeness) && candidate.coverage.population?.trim()
        && candidate.fitnessMetrics && Array.isArray(candidate.trainingLoad?.dailyLoads)
        && candidate.fitnessMetrics.thresholdVersion === candidate.trainingLoad.thresholdVersion
        && candidate.fitnessMetrics.thresholdState === candidate.trainingLoad.thresholdState
        && candidate.fitnessMetrics.thresholdTrainingState === candidate.trainingLoad.thresholdTrainingState
        ? candidate : null;
      return {
        snapshot,
        fitnessMetrics,
        trainingLoad,
      };
    },
    staleTime: 60_000,
  });
}

export function usePowerCurve() {
  return useQuery<PowerCurve>({
    queryKey: queryKeys.analytics.powerCurve(),
    queryFn: () => api.getPowerCurve(),
    staleTime: 60_000,
  });
}

export function useRidingDays(days = 182) {
  return useQuery<RidingDays>({
    queryKey: queryKeys.analytics.ridingDays(days),
    queryFn: () => api.getRidingDays(days),
    staleTime: 60_000,
  });
}
