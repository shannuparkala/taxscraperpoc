/**
 * Tax year selector, limited to the years the rule data supports.
 *
 * A year outside that list is not offered at all - the calculator would
 * refuse it anyway, and offering it would invite a guess.
 */

import { useId } from 'react';

export default function TaxYearSelect({
  years, value, onChange, label = 'Tax year',
}: {
  years: number[];
  value: number;
  onChange: (year: number) => void;
  label?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {[...years].sort((a, b) => b - a).map((year) => (
          <option key={year} value={year}>{year}</option>
        ))}
      </select>
    </div>
  );
}
