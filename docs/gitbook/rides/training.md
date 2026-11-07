# Training

Each ride with power carries a training stress value once your Threshold is
established; an hour at exactly your Threshold is 100. Three metrics are
computed from daily training stress:

| Metric | Definition |
|--------|------------|
| Fitness | Exponentially weighted average of daily training stress, 42-day time constant |
| Fatigue | The same, 7-day time constant |
| Form | Fitness minus Fatigue |

Training stress is computed from your power relative to your Threshold
([Threshold](cal.md#threshold)). Rides without power carry none.

There is one Threshold. CAL uses the value in effect when you started the
ride. Once a raise is scheduled for Monday, training stress, Fitness, Fatigue,
and Form use the scheduled value together and show as pending until that
Monday. Until your Threshold is established, rides show no training stress
([Threshold](cal.md#threshold)).
