/**
 * One assistant reply.
 *
 * A current answer is markdown shaped to the question (`answer_markdown`): a
 * one-line fact stays one line, a notice dispute gets steps. Older stored
 * turns carry the previous fixed layout (Quick answer, Why, Example, ...) and
 * still render through `LegacyAnswer`.
 *
 * Sources are only ever the citations Google Search grounding returned. The
 * [n] markers in the text are placed by the server from grounding metadata,
 * after the answer passed its checks; each one is a chip that scrolls to that
 * source. There is one citation style everywhere, including legacy turns.
 *
 * Follow-up questions are questions *to the reader* ("Which state do you live
 * in?"). They are shown as a prompt to add detail, never as buttons - a
 * button would send the assistant's own question back to it.
 *
 * A fallback, an outage and an out-of-scope reply look different from an
 * answer on purpose, so nobody reads "I couldn't confirm this" as "the answer
 * is nothing".
 */

import { useId } from 'react';

import type { AssistantAnswer, AssistantCitation } from '../../api/client';
import Markdown from './Markdown';

interface Props {
  answer: AssistantAnswer;
}

const REFERENCE_KIND: Record<string, string> = {
  form: 'Form',
  statute: 'Statute',
  regulation: 'Regulation',
  publication: 'Publication',
  agency_guidance: 'Agency guidance',
  court_case: 'Case',
  other: 'Reference',
};

export default function AnswerCard({ answer }: Props) {
  const anchor = useId();
  const answered = answer.status === 'answered' || answer.status === 'declined';

  const jumpTo = (index: number) => {
    document
      .getElementById(`${anchor}-source-${index}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  const md = (text: string) => <Markdown text={text} onCite={jumpTo} />;

  if (answer.status === 'clarify') {
    return (
      <div className="answer answer-clarify-only">
        <Badges answer={answer} />
        <div className="answer-body">{md(answer.answer_markdown || answer.quick_answer)}</div>
      </div>
    );
  }

  if (!answered) {
    return (
      <div className={`answer refusal status-${answer.status}`}>
        <Badges answer={answer} />
        {answer.state_change_notice && (
          <p className="answer-notice">{answer.state_change_notice}</p>
        )}
        <p className="answer-quick">{answer.quick_answer}</p>
        {answer.why && <p className="answer-body">{answer.why}</p>}
        <OfficialLinks answer={answer} />
        <p className="answer-disclaimer">{answer.disclaimer}</p>
      </div>
    );
  }

  return (
    <div className="answer">
      <Badges answer={answer} />

      {answer.state_change_notice && (
        <p className="answer-notice">{answer.state_change_notice}</p>
      )}

      {answer.answer_markdown ? (
        <div className="answer-body answer-markdown">{md(answer.answer_markdown)}</div>
      ) : (
        <LegacyAnswer answer={answer} md={md} />
      )}

      {answer.answer_markdown && answer.considerations.length > 0 && (
        <ul className="answer-notes">
          {answer.considerations.map((item, index) => (
            <li key={index}>{md(item)}</li>
          ))}
        </ul>
      )}

      <FollowUps questions={answer.follow_up_questions} />

      {answer.citations.length > 0 && (
        <Section label="Sources" className="answer-sources-section">
          <ol className="source-list">
            {answer.citations.map((citation) => (
              <SourceItem
                key={citation.index}
                citation={citation}
                anchor={`${anchor}-source-${citation.index}`}
              />
            ))}
          </ol>
          {answer.search_queries.length > 0 && (
            <p className="answer-searched">
              <span className="answer-dates-label">Searched</span>{' '}
              {answer.search_queries.slice(0, 4).join(' · ')}
            </p>
          )}
          <OfficialLinks answer={answer} />
        </Section>
      )}

      {answer.search_suggestions_html && (
        <iframe
          title="Google Search suggestions"
          srcDoc={answer.search_suggestions_html}
          sandbox="allow-popups allow-popups-to-escape-sandbox"
          referrerPolicy="no-referrer"
          className="answer-search-suggestions"
        />
      )}

      <p className="answer-disclaimer">{answer.disclaimer}</p>
    </div>
  );
}

/** The fixed sections of answers stored before answers were shaped to the question. */
function LegacyAnswer({
  answer,
  md,
}: {
  answer: AssistantAnswer;
  md: (text: string) => React.ReactNode;
}) {
  return (
    <>
      <Section label="Quick answer" className="answer-quick-section">
        <div className="answer-quick">{md(answer.quick_answer)}</div>
        {answer.tax_year_note && (answer.tax_year_assumed || answer.tax_year_fallback) && (
          <div className="answer-year-note">{md(answer.tax_year_note)}</div>
        )}
      </Section>

      {answer.why && <Section label="Why">{md(answer.why)}</Section>}

      {answer.state_sections.map((section, index) => (
        <Section
          key={`${section.state_code}-${index}`}
          label={section.heading || section.state_code}
          className="answer-state-section"
        >
          {md(section.content)}
        </Section>
      ))}

      {answer.example && (
        <Section label="Hypothetical example" className="answer-example">
          {md(answer.example)}
        </Section>
      )}

      {(answer.facts_relied_on.length > 0 || answer.assumptions.length > 0) && (
        <Section label="What this answer relies on">
          {answer.facts_relied_on.length > 0 && (
            <BulletList label="Facts from your question" items={answer.facts_relied_on} md={md} />
          )}
          {answer.assumptions.length > 0 && (
            <BulletList label="Assumptions" items={answer.assumptions} md={md} />
          )}
        </Section>
      )}

      {answer.next_steps.length > 0 && (
        <Section label="Next steps">
          <ol className="answer-steps">
            {answer.next_steps.map((step, index) => (
              <li key={index}>
                {md(step.action)}
                {step.deadline && <span className="answer-deadline">{step.deadline}</span>}
              </li>
            ))}
          </ol>
        </Section>
      )}

      {answer.references.length > 0 && (
        <Section label="Forms and authority">
          <ul className="answer-references">
            {answer.references.map((reference, index) => (
              <li key={index}>
                <span className="badge neutral sm">{REFERENCE_KIND[reference.kind] ?? 'Reference'}</span>
                <strong>{reference.label}</strong>
                {reference.description && <> — {md(reference.description)}</>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {(answer.considerations.length > 0 || answer.recent_or_pending_changes.length > 0) && (
        <Section label="Important considerations">
          <ul className="answer-considerations">
            {answer.considerations.map((item, index) => (
              <li key={`c-${index}`}>{md(item)}</li>
            ))}
            {answer.recent_or_pending_changes.map((item, index) => (
              <li key={`r-${index}`} className="change">
                <strong>Recent or pending change: </strong>
                {md(item)}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {answer.unverified_points.length > 0 && (
        <Section label="Could not confirm" className="answer-unverified">
          <ul className="answer-considerations">
            {answer.unverified_points.map((item, index) => (
              <li key={index} className="gap">{md(item)}</li>
            ))}
          </ul>
        </Section>
      )}

      {answer.professional_help.recommended && (
        <p className="answer-escalation">
          <strong>Worth getting professional help.</strong>{' '}
          {answer.professional_help.reason}
        </p>
      )}
    </>
  );
}

function FollowUps({ questions }: { questions: string[] }) {
  if (questions.length === 0) return null;
  return (
    <div className="answer-clarify">
      <span className="answer-dates-label">To tailor this answer, tell me:</span>
      <ul>
        {questions.slice(0, 2).map((question, index) => (
          <li key={index}>{question}</li>
        ))}
      </ul>
    </div>
  );
}

function Badges({ answer }: { answer: AssistantAnswer }) {
  const label =
    answer.status === 'fallback'
      ? 'Not verified'
      : answer.status === 'out_of_scope'
        ? 'US tax questions only'
        : answer.status === 'unavailable'
          ? 'Unavailable'
          : answer.status === 'declined'
            ? 'Cannot help with that'
            : answer.status === 'clarify'
              ? 'One question first'
              : '';
  return (
    <div className="answer-badges">
      {label && <span className="badge warning sm">{label}</span>}
      {answer.states.length === 0 && answer.status === 'answered' && (
        <span className="badge neutral sm">Federal</span>
      )}
      {answer.states.map((state) => (
        <span key={state.code} className="badge accent sm" title={`Answered under ${state.name} rules`}>
          {state.name}
        </span>
      ))}
      {answer.spans_states && <span className="badge info sm">Spans states</span>}
      {answer.tax_year && (
        <span
          className={`badge ${answer.tax_year_fallback ? 'warning' : 'neutral'} sm`}
          title={answer.tax_year_note || undefined}
        >
          Tax year {answer.tax_year}
          {answer.tax_year_fallback && answer.tax_year_requested
            ? ` (${answer.tax_year_requested} not yet published)`
            : answer.tax_year_assumed ? ' (assumed)' : ''}
        </span>
      )}
      {answer.status === 'answered' && answer.confidence === 'low' && (
        <span className="badge warning sm">Low confidence</span>
      )}
      {answer.from_cache && (
        <span className="badge neutral sm" title="The same question was answered earlier today with these sources; ask again tomorrow for a fresh search">
          Answered earlier today
        </span>
      )}
      {answer.was_masked && (
        <span
          className="badge neutral sm"
          title="Personal details you typed were replaced with placeholders before anything was sent"
        >
          Details protected
        </span>
      )}
    </div>
  );
}

function Section({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`answer-section ${className ?? ''}`}>
      <h4>{label}</h4>
      <div className="answer-body">{children}</div>
    </section>
  );
}

function BulletList({
  label,
  items,
  md,
}: {
  label: string;
  items: string[];
  md: (text: string) => React.ReactNode;
}) {
  return (
    <div className="answer-bullets">
      <span className="answer-dates-label">{label}</span>
      <ul>
        {items.map((item, index) => (
          <li key={index}>{md(item)}</li>
        ))}
      </ul>
    </div>
  );
}

function SourceItem({ citation, anchor }: { citation: AssistantCitation; anchor: string }) {
  return (
    <li id={anchor}>
      <a href={citation.url} target="_blank" rel="noreferrer noopener">
        {citation.title}
      </a>
      <span className="source-locator">
        {citation.authority_label}
        {citation.domain && citation.domain !== citation.title ? ` · ${citation.domain}` : ''}
      </span>
    </li>
  );
}

function OfficialLinks({ answer }: { answer: AssistantAnswer }) {
  if (answer.official_links.length === 0) return null;
  return (
    <p className="answer-official">
      <span className="answer-dates-label">Official agency</span>{' '}
      {answer.official_links.map((link, index) => (
        <span key={link.url}>
          {index > 0 && ' · '}
          <a href={link.url} target="_blank" rel="noreferrer noopener">
            {link.label}
          </a>
        </span>
      ))}
    </p>
  );
}
