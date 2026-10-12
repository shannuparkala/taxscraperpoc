import { useId, useState } from 'react';
import { geoAlbersUsa, geoPath } from 'd3-geo';
import { feature } from 'topojson-client';
import type { GeometryCollection, Topology } from 'topojson-specification';
import { MapPin } from 'lucide-react';
import atlas from 'us-atlas/states-10m.json';

import type { StateProfile } from '../../api/client';

const topology = atlas as unknown as Topology<{ states: GeometryCollection<{ name: string }> }>;
const geography = feature(topology, topology.objects.states);
const projection = geoAlbersUsa().scale(640).translate([310, 190]);
const draw = geoPath(projection);
const shapes = geography.features.map((state) => ({
  name: String(state.properties?.name ?? ''),
  path: draw(state),
}));

interface Props {
  profiles: StateProfile[];
  selected: string | null;
  onSelect: (code: string | null) => void;
}

export default function StateMap({ profiles, selected, onSelect }: Props) {
  const selectId = useId();
  const [hovered, setHovered] = useState<string | null>(null);
  const active = profiles.find((profile) => profile.code === selected);
  const byName = new Map(profiles.map((profile) => [profile.name, profile]));

  return (
    <div className="jurisdiction-map">
      <label className="state-select-label" htmlFor={selectId}>State or territory</label>
      <select
        id={selectId}
        value={selected ?? ''}
        onChange={(event) => {
          setHovered(null);
          onSelect(event.target.value || null);
        }}
        disabled={profiles.length === 0}
      >
        <option value="">Federal / no state selected</option>
        {[...profiles].sort((first, second) => first.name.localeCompare(second.name)).map((profile) => (
          <option key={profile.code} value={profile.code}>{profile.name}</option>
        ))}
      </select>
      <svg className="us-state-map" viewBox="0 0 620 400" role="group" aria-label="United States jurisdiction map">
        {shapes.map((shape) => {
          const profile = byName.get(shape.name);
          if (!profile || !shape.path) return null;
          return (
            <path
              key={profile.code}
              d={shape.path}
              className={selected === profile.code ? 'map-state selected' : 'map-state'}
              role="button"
              tabIndex={0}
              aria-label={profile.name}
              aria-pressed={selected === profile.code}
              onClick={() => onSelect(profile.code)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect(profile.code);
                }
              }}
              onMouseEnter={() => setHovered(profile.name)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(profile.name)}
              onBlur={() => setHovered(null)}
            >
              <title>{profile.name}</title>
            </path>
          );
        })}
      </svg>
      <div className="map-selection" aria-live="polite">
        <MapPin size={14} aria-hidden="true" />
        <span>{profiles.length === 0 ? 'States unavailable' : hovered ?? active?.name ?? 'Federal'}</span>
        {active && !hovered && <span className="map-state-code">{active.code}</span>}
      </div>
    </div>
  );
}