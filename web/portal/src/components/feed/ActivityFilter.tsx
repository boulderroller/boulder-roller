import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select';

interface ActivityFilterProps {
  value: string;
  onChange: (value: string) => void;
}

export default function ActivityFilter({ value, onChange }: ActivityFilterProps) {
  const options = [
    { value: 'all', label: 'All rides' },
    { value: 'following', label: 'Following' },
  ];

  return (
    <div className="feed-activity-filter">
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="feed-activity-filter__trigger">
          <SelectValue placeholder="Filter rides" />
        </SelectTrigger>
        <SelectContent className="feed-activity-filter__content">
          {options.map((option) => (
            <SelectItem 
              key={option.value} 
              value={option.value}
              className="feed-activity-filter__item"
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
