/**
 * The assistant's answer rendering: one citation style, follow-ups that are
 * questions to the reader (never buttons), legacy turns without stray
 * markers, and a streamed draft that never shows a marker it cannot back.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import type { AssistantAnswer } from '../api/client';
import AnswerCard from '../components/assistant/AnswerCard';
import Markdown from '../components/assistant/Markdown';

afterEach(cleanup);

function answer(overrides: Partial<AssistantAnswer> = {}): AssistantAnswer {
  return {
    message_id: 'm1', session_id: 's1', status: 'answered', scope: 'us_tax', category: 'fact',
    selected_state: null, state_change_notice: '', jurisdiction_level: 'federal', states: [],
    spans_states: false, tax_year: '2025', tax_year_assumed: true, tax_year_note: '',
    quick_answer: 'The standard deduction for a single filer is $15,750.',
    answer_markdown: 'The standard deduction for a single filer is $15,750 for 2025. [1]',
    answer_type: 'fact', search_queries: ['standard deduction 2025 single'],
    why: '', example: '', state_sections: [], facts_relied_on: [], assumptions: [], references: [],
    next_steps: [], considerations: [], recent_or_pending_changes: [], unverified_points: [],
    follow_up_questions: [], professional_help: { recommended: false, reason: '' },
    confidence: 'high',
    citations: [{
      index: 1, title: 'IRS - standard deduction', url: 'https://www.irs.gov/x', domain: 'irs.gov',
      authority: 'irs', authority_label: 'IRS', state_code: null, supporting_text: '',
    }],
    section_citations: {}, search_suggestions_html: '', official_links: [], validation_issues: [],
    disclaimer: 'General information, not advice.', was_masked: false, model: 'm',
    latency_ms: 1, attempts: 1,
    ...overrides,
  };
}

describe('AnswerCard', () => {
  it('renders a shaped answer with its markers as source chips, and no fixed sections', () => {
    render(<AnswerCard answer={answer()} />);
    expect(screen.getByText(/standard deduction for a single filer/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Source 1' })).toBeTruthy();
    expect(screen.queryByText('[1]')).toBeNull();
    expect(screen.queryByText('Quick answer')).toBeNull();
    expect(screen.queryByText('Why')).toBeNull();
    expect(screen.getByText('Sources')).toBeTruthy();
    expect(screen.getByText(/standard deduction 2025 single/)).toBeTruthy();
  });

  it('shows follow-ups as questions to the reader, at most two, never as buttons', () => {
    render(<AnswerCard answer={answer({
      follow_up_questions: ['Which state do you live in?', 'Are you 65 or older?', 'A third?'],
    })} />);
    expect(screen.getByText('To tailor this answer, tell me:')).toBeTruthy();
    expect(screen.getByText('Which state do you live in?').tagName).toBe('LI');
    expect(screen.queryByRole('button', { name: 'Which state do you live in?' })).toBeNull();
    expect(screen.queryByText('A third?')).toBeNull();
  });

  it('renders markers in every legacy field as chips, never as raw brackets', () => {
    render(<AnswerCard answer={answer({
      answer_markdown: '',
      quick_answer: 'Wages are taxable. [1]',
      unverified_points: ['The 2026 figure was not yet published. [1]'],
      assumptions: ['You file single. [1]'],
    })} />);
    expect(screen.getAllByRole('button', { name: 'Source 1' })).toHaveLength(3);
    expect(document.body.textContent).not.toMatch(/\[1\]/);
  });

  it('shows a clarifying question on its own, with no sources', () => {
    render(<AnswerCard answer={answer({
      status: 'clarify', answer_markdown: 'Which deduction do you mean?', citations: [],
    })} />);
    expect(screen.getByText('Which deduction do you mean?')).toBeTruthy();
    expect(screen.getByText('One question first')).toBeTruthy();
    expect(screen.queryByText('Sources')).toBeNull();
  });
});

describe('Unsourced figures', () => {
  it('renders [?] as a "not matched to a source" flag, not as a source chip', () => {
    render(<Markdown text={'The limit is $7,000 for 2025. [?] Wages are taxable. [1]'} />);
    expect(screen.getByLabelText('Not matched to a source')).toBeTruthy();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(document.body.textContent).not.toContain('[?]');
  });
});

describe('Markdown while streaming', () => {
  it('drops marker-shaped text, since real markers arrive only after the checks', () => {
    render(<Markdown text={'The rate is 10% [3] and [cite: 2, 4] applies.'} stripCitations />);
    expect(document.body.textContent).toBe('The rate is 10% and applies.');
    expect(screen.queryByRole('button')).toBeNull();
  });
});
