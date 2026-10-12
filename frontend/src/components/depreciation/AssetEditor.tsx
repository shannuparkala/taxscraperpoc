/**
 * One asset in the workspace form.
 *
 * Sections appear only when they apply: land for buildings, the SUV cap for
 * heavy vehicles, the 168(n) election for production property. The figures
 * shown beside the elections (the year's Section 179 limit, SUV cap, the
 * bonus rate) come from the rule data and the engine's result, never from
 * the browser.
 */

import { useId } from 'react';
import { Building2, CalendarClock, Car, Factory, Package, Truck } from 'lucide-react';

import type {
  DepreciationAssetClass,
  DepreciationAssetInput,
  DepreciationAssetResult,
  DepreciationRules,
} from '../../api/client';
import { money, reducedBonusElection, withAcquired } from '../../lib/depreciationForm';
import { KeyValue, Label, MoneyInput, PercentInput, Toggle, ToggleSection } from './widgets';

interface Props {
  asset: DepreciationAssetInput;
  classes: DepreciationAssetClass[];
  rules: DepreciationRules;
  use179: boolean;
  useBonus: boolean;
  result: DepreciationAssetResult | null;
  onChange: (asset: DepreciationAssetInput) => void;
}

const METHOD_NAMES: Record<string, string> = {
  '200DB': '200% declining balance',
  '150DB': '150% declining balance',
  SL: 'straight line',
};
const CONVENTION_NAMES: Record<string, string> = { HY: 'Half-year', MQ: 'Mid-quarter', MM: 'Mid-month' };

/**
 * The convention selector. Personal property may use half-year or
 * mid-quarter; buildings use mid-month. The other combinations have no IRS
 * table, so they are shown but disabled rather than hidden - the reader can
 * see the option exists and why it does not apply here.
 */
function ConventionSelect({
  id, value, realProperty, onChange,
}: {
  id: string; value: string | null | undefined; realProperty: boolean; onChange: (value: string | null) => void;
}) {
  if (realProperty) {
    return (
      <select id={id} value="MM" disabled title="Buildings always use the mid-month convention.">
        <option value="MM">Mid-month (required for buildings)</option>
      </select>
    );
  }
  return (
    <select id={id} value={value ?? ''} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">Automatic (40% test)</option>
      <option value="HY">Half-year</option>
      <option value="MQ">Mid-quarter</option>
      <option value="MM" disabled>Mid-month (buildings only)</option>
    </select>
  );
}

function classIcon(key: string) {
  if (key === 'passenger_vehicle') return <Car size={15} />;
  if (key === 'heavy_vehicle') return <Truck size={15} />;
  if (key === 'residential_rental' || key === 'nonresidential') return <Building2 size={15} />;
  if (key === 'qualified_production') return <Factory size={15} />;
  return <Package size={15} />;
}

export default function AssetEditor({ asset, classes, rules, use179, useBonus, result, onChange }: Props) {
  const id = useId();
  const f = (suffix: string) => `${id}-${suffix}`;
  const cls = classes.find((c) => c.key === asset.asset_class);
  const set = <K extends keyof DepreciationAssetInput>(key: K, value: DepreciationAssetInput[K]) => onChange({ ...asset, [key]: value });
  const pisYear = asset.placed_in_service.slice(0, 4);
  const limits = (rules.federal.section_179 as Record<string, { limit: number; phaseout_threshold: number; suv_cap: number }>)[pisYear];
  const listedLow = cls?.listed && Number(asset.business_use_pct) <= 50;
  const reduced = reducedBonusElection(rules.federal);

  const methodAndConvention = (
    <div className="dw-field">
      <Label
        htmlFor={f('conv')}
        info="Automatic applies the law: mid-quarter when more than 40% of the year's personal-property basis (after Section 179, before bonus) is placed in service in Q4, otherwise half-year; buildings always use mid-month. Choosing half-year or mid-quarter overrides that test - mid-quarter still uses the placed-in-service quarter to pick its table - and the results warn you when your choice differs from what the test requires."
      >
        Method and convention
      </Label>
      <ConventionSelect id={f('conv')} value={asset.convention} realProperty={Boolean(cls?.real_property)}
        onChange={(v) => set('convention', v)} />
      <div className="dw-readout">
        {result
          ? <>{result.system} {METHOD_NAMES[result.method] ?? result.method} · <strong>{CONVENTION_NAMES[result.convention]}</strong>
            {result.convention_selected ? ' (selected)' : ' (automatic)'}</>
          : <span className="muted">Method shown after calculation</span>}
      </div>
    </div>
  );

  return (
    <div className="dw-asset">
      <div className="dw-field full">
        <Label htmlFor={f('desc')} info="For your own reference. It is never sent to the AI explanation.">Asset description (optional)</Label>
        <input id={f('desc')} type="text" maxLength={120} value={asset.description} placeholder="e.g. Delivery van"
          onChange={(e) => set('description', e.target.value)} />
      </div>

      <div className="dw-row2">
        <div className="dw-field">
          <Label htmlFor={f('class')} info="Determines the recovery period and method under GDS (IRS Pub. 946, ch. 4).">Asset class</Label>
          <div className="dw-select-icon">
            <span aria-hidden="true">{classIcon(asset.asset_class)}</span>
            <select id={f('class')} value={asset.asset_class} onChange={(e) => {
              const next = classes.find((c) => c.key === e.target.value);
              // A convention chosen for personal property has no table for a
              // building, and vice versa: drop it when the kind changes.
              const keep = next && Boolean(next.real_property) === Boolean(cls?.real_property);
              onChange({ ...asset, asset_class: e.target.value, convention: keep ? asset.convention ?? null : null });
            }}>
              {classes.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.recovery_years ? `${c.recovery_years} years — ` : ''}{c.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {cls?.key === 'other' ? (
          <div className="dw-field">
            <Label htmlFor={f('period')} info="Choose from Pub. 946 Appendix B. 3-10 years use 200% DB; 15-20 years use 150% DB.">Recovery period</Label>
            <select id={f('period')} value={asset.recovery_years ?? '7'} onChange={(e) => set('recovery_years', e.target.value)}>
              {cls.allowed_recovery_years.map((y) => <option key={y} value={y}>{y} years</option>)}
            </select>
          </div>
        ) : methodAndConvention}
      </div>
      {cls?.key === 'other' && (
        <div className="dw-row2">
          {methodAndConvention}
          <div />
        </div>
      )}
      {cls?.note && <p className="dw-hint">{cls.note}</p>}

      <div className="dw-row2">
        <div className="dw-field">
          <Label htmlFor={f('cost')} info="Purchase price plus sales tax, freight and installation.">Cost basis</Label>
          <MoneyInput id={f('cost')} value={asset.cost} onChange={(v) => set('cost', v)} placeholder="0" grouped />
        </div>
        {(cls?.real_property || cls?.key === 'land_improvements') ? (
          <div className="dw-field">
            <Label htmlFor={f('land')} info="Land is never depreciable; its value is removed from the basis.">Land value included</Label>
            <MoneyInput id={f('land')} value={asset.land_value} onChange={(v) => set('land_value', v)} />
          </div>
        ) : (cls?.key === 'passenger_vehicle' || cls?.key === 'heavy_vehicle') ? (
          <div className="dw-field">
            <Label htmlFor={f('credit')} info="The vehicle's basis is reduced by any clean vehicle credit claimed for it.">Clean vehicle credit</Label>
            <MoneyInput id={f('credit')} value={asset.clean_vehicle_credit} onChange={(v) => set('clean_vehicle_credit', v)} />
          </div>
        ) : <div />}
      </div>

      <div className="dw-row2">
        <div className="dw-field">
          <Label htmlFor={f('acq')} info="Sets the bonus rate: property acquired after Jan. 19, 2025 gets 100%. A binding contract signed earlier counts as acquired earlier. The placed-in-service date follows this date until you change it.">Date acquired</Label>
          <div className="dw-date"><CalendarClock size={14} aria-hidden="true" />
            <input id={f('acq')} type="date" value={asset.acquired ?? ''} onChange={(e) => onChange(withAcquired(asset, e.target.value))} />
          </div>
        </div>
        <div className="dw-field">
          <Label htmlFor={f('pis')} info="Depreciation starts in the year the asset is ready and available for use, not when it was bought.">Placed-in-service date</Label>
          <div className="dw-date"><CalendarClock size={14} aria-hidden="true" />
            <input id={f('pis')} type="date" value={asset.placed_in_service} onChange={(e) => set('placed_in_service', e.target.value)} />
          </div>
        </div>
      </div>

      <div className="dw-divider" />

      {cls?.section_179_eligible && (
        <ToggleSection
          title="Section 179 deduction"
          info="Expense the cost in the first year, up to the annual limit, reduced dollar for dollar above the phase-out threshold, and limited to business income."
          checked={use179 && asset.section_179_amount !== '0'}
          onChange={(on) => set('section_179_amount', on ? null : '0')}
          disabled={!use179 || Boolean(listedLow)}
          hint={!use179 ? 'Turned off under Elections.' : asset.section_179_amount === '0' ? 'No Section 179 on this asset.' : undefined}
        >
          <div className="dw-kv-box">
            {limits && <KeyValue label={`Annual limit (${pisYear})`} value={money(String(limits.limit))} />}
            {limits && <KeyValue label={`Phase-out threshold (${pisYear})`} value={money(String(limits.phaseout_threshold))} />}
            {cls.suv_cap && limits && <KeyValue label="SUV cap (over 6,000 lb)" value={money(String(limits.suv_cap))} />}
            {result && <KeyValue label="Elected on this asset" value={money(result.section_179_elected)} strong />}
          </div>
          <div className="dw-field">
            <Label htmlFor={f('s179')} info="Leave blank to elect the maximum allowed. Basis is reduced by the amount elected.">Override amount (optional)</Label>
            <MoneyInput id={f('s179')} value={asset.section_179_amount ?? ''} placeholder="Auto (max allowed)"
              onChange={(v) => set('section_179_amount', v || null)} />
          </div>
        </ToggleSection>
      )}

      {cls?.listed && (
        <ToggleSection
          title="Listed property"
          info="Vehicles are listed property. At 50% or less business use, ADS straight line is required and Section 179 and bonus are not allowed."
          checked
          badge="Listed"
        >
          <div className="dw-field">
            <Label htmlFor={f('use')} info="Only the business-use share of the basis is depreciable.">Business-use %</Label>
            <PercentInput id={f('use')} value={asset.business_use_pct} onChange={(v) => set('business_use_pct', v)} min={1} />
            {listedLow && <p className="dw-hint warn">50% or less: ADS straight line, no Section 179 or bonus.</p>}
          </div>
          <div className="dw-inline-toggle">
            <span><Truck size={14} aria-hidden="true" /> Vehicle over 6,000 lb GVWR</span>
            <span className="badge neutral">{cls.key === 'heavy_vehicle' ? 'Yes — no §280F caps' : 'No — §280F caps apply'}</span>
          </div>
          {cls.suv_cap && (
            <div className="dw-inline-toggle">
              <span>Exempt from the SUV cap (6 ft+ bed, 9+ seats behind driver, or cargo van)</span>
              <Toggle checked={asset.suv_cap_exempt} onChange={(v) => set('suv_cap_exempt', v)} label="Exempt from the SUV cap" />
            </div>
          )}
        </ToggleSection>
      )}

      {!cls?.listed && !cls?.real_property && (
        <div className="dw-field">
          <Label htmlFor={f('use')} info="Only the business-use share of the basis is depreciable.">Business-use %</Label>
          <PercentInput id={f('use')} value={asset.business_use_pct} onChange={(v) => set('business_use_pct', v)} min={1} />
        </div>
      )}

      {cls?.bonus_eligible && (
        <ToggleSection
          title="Bonus depreciation"
          info="Sec. 168(k) special allowance on the basis left after Section 179. The rate depends on when the asset was acquired and placed in service."
          checked={useBonus && !asset.elect_out_bonus}
          onChange={(on) => set('elect_out_bonus', !on)}
          disabled={!useBonus || Boolean(listedLow)}
          hint={!useBonus ? 'Turned off under Elections.' : asset.elect_out_bonus ? 'Elected out — applies to every asset in this class placed in service this year.' : undefined}
        >
          <div className="dw-kv-box">
            <KeyValue label={`Bonus % for ${pisYear}`} value={<span className="dw-pill">{result ? `${Number(result.bonus_rate)}%` : '—'}</span>} />
            {result && <KeyValue label="First-year bonus" value={money(result.bonus)} strong />}
          </div>
          {reduced && reduced.years.includes(Number(pisYear)) && (
            <div className="dw-inline-toggle">
              <span>Elect {reduced.rate}% instead of 100% ({reduced.years.join(', ')} only)</span>
              <Toggle checked={asset.elect_reduced_bonus} onChange={(v) => set('elect_reduced_bonus', v)} label={`Elect ${reduced.rate}% bonus`} />
            </div>
          )}
        </ToggleSection>
      )}

      {cls?.qpp && (
        <ToggleSection
          title="Section 168(n) allowance"
          info="Elective 100% allowance for the production portion of a nonresidential building: construction begun after Jan. 19, 2025 and before 2029, placed in service after July 4, 2025 and before 2031."
          checked={asset.qpp_elect}
          onChange={(v) => set('qpp_elect', v)}
        >
          <div className="dw-field">
            <Label htmlFor={f('qpp')}>Construction began</Label>
            <div className="dw-date"><CalendarClock size={14} aria-hidden="true" />
              <input id={f('qpp')} type="date" value={asset.qpp_construction_began ?? ''} onChange={(e) => set('qpp_construction_began', e.target.value || null)} />
            </div>
          </div>
        </ToggleSection>
      )}
    </div>
  );
}
