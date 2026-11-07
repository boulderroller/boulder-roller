export const DESIGNS = [
  { id: 'current', label: 'Current' },
  { id: 'candidate', label: 'Candidate v1' },
  { id: 'candidate-v2', label: 'Candidate v2' },
  { id: 'candidate-v3', label: 'Candidate v3' },
  { id: 'candidate-v4', label: 'Candidate v4' },
  { id: 'candidate-v5', label: 'Candidate v5' },
  { id: 'candidate-v6', label: 'Candidate v6' },
  { id: 'candidate-v7', label: 'Candidate v7' },
  { id: 'candidate-v8', label: 'Candidate v8' },
  { id: 'candidate-v9', label: 'Candidate v9' },
  { id: 'candidate-v10', label: 'Candidate v10' },
  { id: 'candidate-v11', label: 'Candidate v11' },
  { id: 'candidate-v12', label: 'Candidate v12' },
  { id: 'candidate-v13', label: 'Candidate v13' },
  { id: 'candidate-v14', label: 'Candidate v14' },
] as const;

export type DesignVariant = typeof DESIGNS[number]['id'];
export const isDesignVariant = (value: unknown): value is DesignVariant => DESIGNS.some(design => design.id === value);
export const designFromQuery = (value: string | null): DesignVariant => isDesignVariant(value) ? value : 'candidate-v12';
